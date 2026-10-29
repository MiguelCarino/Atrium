"""The launcher's passwords (scripts/launcher_secrets.py): who the Secret
Service provider is, the search over names and attributes, the scan of a
fake provider's collections, and the copy-then-clear holder with a fake
clipboard. No bus, no clipboard, no real secret."""
import subprocess
import time
import unittest

import helpers

S = helpers.import_script("launcher_secrets.py")


class Pure(unittest.TestCase):
    def test_provider_label(self):
        owners = {"org.keepassxc.KeePassXC.MainWindow": ":1.9", "org.gnome.keyring": ":1.4"}
        self.assertEqual(S.provider_label(":1.9", owners), "KeePassXC")
        self.assertEqual(S.provider_label(":1.4", owners), "GNOME Keyring")
        self.assertEqual(S.provider_label(":1.7", owners), "Secret Service")
        self.assertEqual(S.provider_label(None, owners), "Secret Service")

    def test_safe_attrs_drop_what_looks_secret(self):
        got = S.safe_attrs({"UserName": "me", "Notes": "pin 1234", "TOTP": "x", "Uuid": "u",
                            "URL": "example.org", "api_token": "t", "xdg:schema": "s"})
        self.assertEqual(got, {"UserName": "me", "URL": "example.org"})

    def test_search(self):
        rows = [{"path": p, "label": l, "attrs": a, "text": S.searchable(l, a)} for p, l, a in (
            ("/1", "Mail", {"UserName": "me", "URL": "mail.example.org"}),
            ("/2", "Example forum", {"UserName": "someone"}),
            ("/3", "Bank", {"Notes": "example"}))]
        self.assertEqual([r["path"] for r in S.search(rows, "example")], ["/2", "/1"])   # label start first
        self.assertEqual([r["path"] for r in S.search(rows, "mail me")], ["/1"])
        self.assertEqual(len(S.search(rows, "")), 3)
        self.assertEqual(S.search(rows, "bank example"), [])     # notes are never searched
        self.assertEqual(len(S.search(rows * 10, "", limit=4)), 4)

    def test_subtitle(self):
        sub = S.subtitle({"label": "Mail", "attrs": {"UserName": "me", "URL": "mail.example.org"}}, "KeePassXC")
        self.assertTrue(sub.startswith("me · mail.example.org  ·  KeePassXC: Enter copies"))
        self.assertIn(f"{S.CLEAR_AFTER} s", sub)
        self.assertTrue(S.subtitle({"label": "x", "attrs": {}}, "GNOME Keyring").startswith("GNOME Keyring:"))

    def test_same_secret(self):
        self.assertTrue(S.same_secret(b"hunter2", b"hunter2"))
        self.assertTrue(S.same_secret(b"hunter2\n", b"hunter2"))     # wl-paste -n dropped the newline
        self.assertFalse(S.same_secret(b"hunter2", b"something else"))
        self.assertFalse(S.same_secret(b"hunter2", None))


class Hold(unittest.TestCase):
    def fake(self, codes, pasted):
        calls = []

        def run(argv, **kw):
            calls.append((argv, kw.get("input")))
            return subprocess.CompletedProcess(argv, codes.pop(0) if codes else 0)
        return calls, run, (lambda: pasted)

    def test_copies_on_stdin_then_clears(self):
        calls, run, paste = self.fake([0], b"s3cret")
        said = []
        got = S.hold(b"s3cret", 30, run=run, sleep=lambda s: said.append(("slept", s)), paste=paste,
                     copied=lambda: said.append("copied"))
        self.assertEqual(got, "cleared")
        self.assertEqual(calls[0], (["wl-copy", "--sensitive"], b"s3cret"))
        self.assertEqual(calls[-1][0], ["wl-copy", "--clear"])
        self.assertEqual(said, ["copied", ("slept", 30)])
        self.assertTrue(all(b"s3cret" not in " ".join(a).encode() for a, _ in calls))   # never in an argv

    def test_something_copied_since_is_left_alone(self):
        calls, run, paste = self.fake([0], b"other")
        self.assertEqual(S.hold(b"s3cret", 30, run=run, sleep=lambda s: None, paste=paste), "kept")
        self.assertNotIn(["wl-copy", "--clear"], [a for a, _ in calls])

    def test_old_wl_copy_without_sensitive(self):
        calls, run, paste = self.fake([2, 0], b"s3cret")
        self.assertEqual(S.hold(b"s3cret", 1, run=run, sleep=lambda s: None, paste=paste), "cleared")
        self.assertEqual([a for a, _ in calls][:2], [["wl-copy", "--sensitive"], ["wl-copy"]])

    def test_no_clipboard(self):
        _calls, run, paste = self.fake([1, 1], None)
        self.assertEqual(S.hold(b"x", 1, run=run, sleep=lambda s: None, paste=paste), "failed")


class FakeProvider:
    """A Secret Service on a fake bus: collections {path: (locked, {item: props})}."""

    def __init__(self, owner=":1.9", collections=None, secrets=None, owners=None):
        self.owner = owner
        self.collections = collections or {}
        self.secrets = secrets or {}
        self.owners = owners or {"org.keepassxc.KeePassXC.MainWindow": ":1.9"}
        self.calls = []

    def call(self, bus, path, iface, method, params, reply, timeout=None):
        self.calls.append((path, method))
        if method == "GetNameOwner":
            name = params[0]
            got = self.owner if name == S.BUS else self.owners.get(name)
            if not got:
                raise RuntimeError("no owner")
            return (got,)
        if method == "Get":
            iface_, prop = params
            if path == S.ROOT:
                return (list(self.collections),)
            locked, items = self.collections[path]
            return (locked,) if prop == "Locked" else (list(items),)
        if method == "GetAll":
            for _locked, items in self.collections.values():
                if path in items:
                    return (items[path],)
            raise RuntimeError("gone")
        if method == "OpenSession":
            return ("", "/s/1")
        if method == "GetSecret":
            if path not in self.secrets:
                raise RuntimeError("locked")
            return (("/s/1", b"", self.secrets[path], "text/plain"),)
        if method == "Close":
            return ()
        if method == "Unlock":
            return ([], "/")
        raise AssertionError(method)


def service(fake):
    return S.SecretService(call=fake.call, variant=lambda fmt, *values: values)


class Scan(unittest.TestCase):
    def test_nothing_running(self):
        got = service(FakeProvider(owner=None)).scan()
        self.assertEqual((got["state"], got["provider"]), ("none", "Secret Service"))

    def test_nothing_shared(self):
        self.assertEqual(service(FakeProvider()).scan()["state"], "empty")

    def test_locked(self):
        got = service(FakeProvider(collections={"/c/1": (True, {})})).scan()
        self.assertEqual((got["state"], got["locked"], got["provider"]), ("locked", ["/c/1"], "KeePassXC"))

    def test_open_items_without_secret_attributes(self):
        fake = FakeProvider(collections={
            "/c/1": (False, {"/c/1/a": {"Label": "Mail", "Locked": False,
                                        "Attributes": {"UserName": "me", "Notes": "hush"}}}),
            "/c/2": (True, {})})
        got = service(fake).scan()
        self.assertEqual(got["state"], "ok")
        self.assertEqual(got["locked"], ["/c/2"])
        self.assertEqual(got["items"], [{"path": "/c/1/a", "label": "Mail", "attrs": {"UserName": "me"},
                                         "text": "mail me"}])
        self.assertNotIn("GetSecret", [m for _, m in fake.calls])     # a scan never reads a secret

    def test_secret_and_session_closed(self):
        fake = FakeProvider(secrets={"/c/1/a": b"pw"})
        self.assertEqual(service(fake).secret("/c/1/a"), b"pw")
        self.assertEqual(fake.calls[-1], ("/s/1", "Close"))
        self.assertIsNone(service(fake).secret("/c/1/b"))

    def test_unlock_without_prompt(self):
        self.assertTrue(service(FakeProvider()).unlock(["/c/1"]))


class Copy(unittest.TestCase):
    def setUp(self):
        self._hold = S.hold
        self.held = []
        S.hold = lambda secret, seconds, copied=lambda: None, **kw: (self.held.append((secret, seconds)),
                                                                     copied(), "cleared")[-1]

    def tearDown(self):
        S.hold = self._hold

    def test_copy_says_the_name_never_the_secret(self):
        fake = FakeProvider(collections={"/c/1": (False, {"/c/1/a": {"Label": "Mail"}})},
                            secrets={"/c/1/a": b"pw-123"})
        fake_get = fake.call

        def call(bus, path, iface, method, params, reply, timeout=None):
            if method == "Get" and path == "/c/1/a":
                return ("Mail",)
            return fake_get(bus, path, iface, method, params, reply, timeout)
        fake.call = call
        said = []
        got = S.copy("/c/1/a", 30, service=service(fake), say=lambda *a: said.append(a))
        self.assertEqual(got, "cleared")
        self.assertEqual(self.held, [(b"pw-123", 30)])
        self.assertEqual(said[0][0], "Password copied")
        self.assertTrue(all("pw-123" not in " ".join(a) for a in said))

    def test_unreadable(self):
        said = []
        self.assertEqual(S.copy("/x", 30, service=service(FakeProvider()), say=lambda *a: said.append(a)), "unread")
        self.assertEqual(self.held, [])
        self.assertIn("no password copied", said[0][0])


class IndexCache(unittest.TestCase):
    def test_scans_in_a_thread_then_keeps_it(self):
        scans = []

        class Svc:
            def scan(self):
                scans.append(1)
                return {"state": "ok", "provider": "X", "items": [], "locked": []}
        ready = []
        idx = S.Index(service=Svc(), on_ready=lambda: ready.append(1))
        self.assertIsNone(idx.get(now=0))
        for _ in range(100):
            if ready:
                break
            time.sleep(0.01)
        self.assertEqual(idx.get()["state"], "ok")
        self.assertEqual(len(scans), 1)
        idx.forget()
        self.assertIsNone(idx.result)

    def test_argv_holds_the_path_only(self):
        argv = S.copy_argv("/org/freedesktop/secrets/collection/x/1", 30)
        self.assertEqual(argv[-3:], ["copy", "/org/freedesktop/secrets/collection/x/1", "30"])
        self.assertEqual(S.unlock_argv(["/c/1"])[-2:], ["unlock", "/c/1"])


if __name__ == "__main__":
    unittest.main()
