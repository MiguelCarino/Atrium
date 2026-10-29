"""hyprbus.py: the pure parts (names, hello, routing, the instance folder),
then the relay end to end against a fake socket2 in the scratch runtime
folder -- filters, the fallback to socket2 with no relay, a slow subscriber
dropped instead of waited on, and a Hyprland restart.

Hermetic: the fake Hyprland is a unix socket under helpers' scratch
XDG_RUNTIME_DIR; nothing reaches the real one."""
import os
import socket
import tempfile
import threading
import time
import unittest
import unittest.mock

import helpers

hb = helpers.import_script("hyprbus.py")


class Pure(unittest.TestCase):
    def test_event_name(self):
        self.assertEqual(hb.event_name(b"openwindow>>a,b,c"), b"openwindow")
        self.assertEqual(hb.event_name(b"configreloaded>>"), b"configreloaded")

    def test_hello_round_trip(self):
        self.assertEqual(hb.hello({"b", "a"}), b"a b\n")
        self.assertEqual(hb.parse_hello(b"a b\n"), frozenset({b"a", b"b"}))
        self.assertIs(hb.parse_hello(hb.hello(hb.ALL)), hb.ALL)
        self.assertEqual(hb.parse_hello(b"?\n"), "status")

    def test_bad_names(self):
        for bad in ([], ["a>>b"], ["with space"], [""]):
            with self.assertRaises(ValueError):
                hb.hello(bad)
        self.assertEqual(hb.parse_hello(b"\n"), "")
        self.assertEqual(hb.parse_hello(b"x>>y\n"), "")

    def test_split_lines_keeps_the_unfinished_line(self):
        lines, rest = hb.split_lines(b"open", b"window>>1\nclose")
        self.assertEqual((lines, rest), ([b"openwindow>>1"], b"close"))

    def test_route_one_write_per_subscriber_and_none_empty(self):
        lines = [b"windowtitle>>1", b"openwindow>>2", b"windowtitlev2>>3"]
        out = hb.route(lines, {1: frozenset({b"openwindow"}), 2: hb.ALL,
                               3: frozenset({b"configreloaded"}), 4: frozenset({b"windowtitle"})})
        self.assertEqual(out[1], b"openwindow>>2\n")
        self.assertEqual(out[2], b"\n".join(lines) + b"\n")
        self.assertNotIn(3, out)
        self.assertEqual(out[4], b"windowtitle>>1\n")    # exact names: not windowtitlev2

    def test_instance_dir_prefers_live_env_then_newest(self):
        base = tempfile.mkdtemp(dir=os.environ["XDG_RUNTIME_DIR"])
        for name, age in (("old", 100), ("new", 10)):
            os.makedirs(os.path.join(base, name))
            open(os.path.join(base, name, ".socket2.sock"), "w").close()
            os.utime(os.path.join(base, name), (time.time() - age,) * 2)
        self.assertEqual(hb.instance_dir(base, "old"), os.path.join(base, "old"))
        self.assertEqual(hb.instance_dir(base, "gone"), os.path.join(base, "new"))
        self.assertEqual(hb.instance_dir(base, ""), os.path.join(base, "new"))
        self.assertIsNone(hb.instance_dir(os.path.join(base, "nothing"), ""))


class FakeHyprland:
    """A socket2 that accepts readers and writes what it is told to all of them."""

    def __init__(self, path):
        self.path = path
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(path)
        self.server.listen(16)
        self.server.settimeout(0.05)
        self.clients, self.lock, self.stopped = [], threading.Lock(), False
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while not self.stopped:
            try:
                c, _ = self.server.accept()
            except (socket.timeout, OSError):
                continue
            with self.lock:
                self.clients.append(c)

    def readers(self):
        with self.lock:
            return len(self.clients)

    def send(self, data):
        with self.lock:
            for c in self.clients:
                c.sendall(data)

    def stop(self):
        self.stopped = True
        with self.lock:
            for c in self.clients:
                c.close()
        self.server.close()
        os.unlink(self.path)


def wait_for(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def read_until(sock, want, timeout=3.0):
    sock.settimeout(timeout)
    data = b""
    while want not in data:
        chunk = sock.recv(65536)
        if not chunk:
            break
        data += chunk
    return data


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(dir=os.environ["XDG_RUNTIME_DIR"])
        self.s2 = os.path.join(self.dir, ".socket2.sock")
        self.relay_path = os.path.join(self.dir, "hyprbus.sock")
        self.hypr = FakeHyprland(self.s2)
        self.target = {"path": self.s2}
        self.relay = hb.Relay(path=self.relay_path, find=lambda: self.target["path"],
                              log=lambda _m: None, limit=4096)
        self.stop = False
        self.thread = threading.Thread(target=self.relay.run, kwargs={"stop": lambda: self.stop}, daemon=True)
        self.thread.start()
        self.assertTrue(wait_for(lambda: os.path.exists(self.relay_path)))
        self.socks = []

    def tearDown(self):
        self.stop = True                # the relay sees it when the fake Hyprland below goes away
        for s in self.socks:
            s.close()
        if not self.hypr.stopped:
            self.hypr.stop()
        self.thread.join(3)

    def sub(self, names):
        s = hb.connect(names, direct="/nonexistent", relay=self.relay_path)
        self.socks.append(s)
        self.assertTrue(wait_for(lambda: len(self.relay.subs) >= len(self.socks)))
        return s

    def test_one_socket2_reader_and_filters(self):
        a = self.sub({"openwindow"})
        b = self.sub(hb.ALL)
        self.assertEqual(self.hypr.readers(), 1)
        self.hypr.send(b"windowtitle>>x\nopenwindow>>1,2,3,4\nconfigre")
        self.hypr.send(b"loaded>>\n")
        self.assertEqual(read_until(a, b"openwindow>>1,2,3,4\n"), b"openwindow>>1,2,3,4\n")
        self.assertEqual(read_until(b, b"configreloaded>>\n"),
                         b"windowtitle>>x\nopenwindow>>1,2,3,4\nconfigreloaded>>\n")
        st = hb.status(self.relay_path)
        self.assertEqual(st["lines"], 3)
        self.assertEqual(len(st["subscribers"]), 2)

    def test_slow_subscriber_is_dropped_not_waited_on(self):
        slow = self.sub({"windowtitle"})
        slow.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
        fast = self.sub({"openwindow"})
        line = b"windowtitle>>" + b"x" * 1000 + b"\n"
        for _ in range(400):                         # far more than the 4 KiB limit + socket buffers
            self.hypr.send(line)
        self.hypr.send(b"openwindow>>ok\n")
        self.assertEqual(read_until(fast, b"openwindow>>ok\n"), b"openwindow>>ok\n")
        self.assertTrue(wait_for(lambda: self.relay.counts["dropped"] == 1))
        self.assertEqual(len(self.relay.subs), 1)

    def test_hyprland_restart_ends_streams_then_follows_the_new_one(self):
        a = self.sub({"openwindow"})
        self.hypr.stop()
        a.settimeout(3)
        self.assertEqual(a.recv(100), b"")           # the end, as a direct reader would see it
        self.socks.remove(a)
        a.close()
        self.assertTrue(wait_for(lambda: not os.path.exists(self.relay_path)))
        new = os.path.join(self.dir, "new.socket2.sock")
        self.hypr = FakeHyprland(new)
        self.target["path"] = new
        self.assertTrue(wait_for(lambda: os.path.exists(self.relay_path)))
        b = self.sub({"openwindow"})
        self.hypr.send(b"openwindow>>again\n")
        self.assertEqual(read_until(b, b"again\n"), b"openwindow>>again\n")


class OneBatch(unittest.TestCase):
    def test_hyprland_gone_and_a_connection_in_one_select(self):
        """detach() runs on Hyprland's end; the listener's key from the same
        select() must then be skipped, not accept() on a closed listener."""
        relay = hb.Relay(path="/nonexistent", find=lambda: None, log=lambda _m: None)
        relay.hypr = unittest.mock.Mock(recv=unittest.mock.Mock(return_value=b""))
        relay.listener = unittest.mock.Mock()
        relay.sel = unittest.mock.Mock()
        key = lambda what: unittest.mock.Mock(fd=7, data=what)
        relay.sel.select.return_value = [(key("hypr"), 1), (key("listen"), 1)]
        relay.step(0)                   # raised AttributeError before the guard
        self.assertIsNone(relay.hypr)
        self.assertIsNone(relay.listener)


class Fallback(unittest.TestCase):
    def test_no_relay_goes_direct(self):
        d = tempfile.mkdtemp(dir=os.environ["XDG_RUNTIME_DIR"])
        fake = FakeHyprland(os.path.join(d, ".socket2.sock"))
        try:
            s = hb.connect({"openwindow"}, direct=fake.path, relay=os.path.join(d, "none.sock"))
            with s:
                self.assertTrue(wait_for(lambda: fake.readers() == 1))
                fake.send(b"windowtitle>>t\n")
                self.assertEqual(read_until(s, b"\n"), b"windowtitle>>t\n")    # unfiltered: as before
        finally:
            fake.stop()

    def test_direct_may_be_a_function(self):
        d = tempfile.mkdtemp(dir=os.environ["XDG_RUNTIME_DIR"])
        fake = FakeHyprland(os.path.join(d, ".socket2.sock"))
        try:
            with hb.connect({"openwindow"}, direct=lambda: fake.path, relay=os.path.join(d, "none.sock")):
                self.assertTrue(wait_for(lambda: fake.readers() == 1))
            with self.assertRaises(OSError):
                hb.connect({"openwindow"}, direct=lambda: None, relay=os.path.join(d, "none.sock"))
        finally:
            fake.stop()

    def test_nothing_reachable_raises(self):
        with self.assertRaises(OSError):
            hb.connect({"openwindow"}, direct="/nonexistent/.socket2.sock", relay="/nonexistent/r.sock")

    def test_off_switch(self):
        d = tempfile.mkdtemp(dir=os.environ["XDG_RUNTIME_DIR"])
        fake = FakeHyprland(os.path.join(d, ".socket2.sock"))
        os.environ["HYPRBUS_OFF"] = "1"
        try:
            with hb.connect(hb.ALL, direct=fake.path, relay=os.path.join(d, "any.sock")):
                self.assertTrue(wait_for(lambda: fake.readers() == 1))
        finally:
            del os.environ["HYPRBUS_OFF"]
            fake.stop()

    def test_subscribe_filters_a_direct_stream(self):
        d = tempfile.mkdtemp(dir=os.environ["XDG_RUNTIME_DIR"])
        fake = FakeHyprland(os.path.join(d, ".socket2.sock"))
        try:
            it = hb.subscribe({"configreloaded"}, direct=fake.path, relay=os.path.join(d, "none.sock"))
            got = []
            t = threading.Thread(target=lambda: got.append(next(it)), daemon=True)
            t.start()
            self.assertTrue(wait_for(lambda: fake.readers() == 1))
            fake.send(b"windowtitle>>t\nconfigreloaded>>\n")
            t.join(3)
            self.assertEqual(got, [("configreloaded", "")])
        finally:
            fake.stop()


class Readers(unittest.TestCase):
    """The daemons that subscribe: each asks for every event name it reads
    (a name missing here would never reach it through the relay)."""

    def test_names_cover_what_each_reads(self):
        cw = helpers.import_script("closed-windows.py")
        self.assertLessEqual(cw.DIRTY | {"openwindow", "closewindow"}, cw.HYPR_EVENTS)
        al = helpers.import_script("activity-log.py")
        self.assertEqual(al.HYPR_EVENTS, {"activewindow", "workspace", "focusedmon"})
        gp = helpers.import_script("game-profiles.py")
        self.assertLessEqual({"openwindow", "closewindow", "windowtitle", "windowtitlev2"}, gp.HYPR_EVENTS)
        sg = helpers.import_script("suggest.py")
        self.assertEqual(set(sg.HYPR_EVENTS), {"activewindowv2", "fullscreen", "screencast"})
        fg = helpers.import_script("focus-guard.py")
        self.assertEqual(set(fg.HYPR_EVENTS), {"activewindow", "activewindowv2", "openwindow",
                                               "windowtitlev2", "closewindow", "configreloaded"})
        for names in (cw.HYPR_EVENTS, al.HYPR_EVENTS, gp.HYPR_EVENTS, sg.HYPR_EVENTS, fg.HYPR_EVENTS):
            hb.hello(names)                     # all valid names

    def test_suggest_connect_events_passes_the_names(self):
        import hyprbus                          # the module suggest.py imports by name
        sg = helpers.import_script("suggest.py")
        seen = []
        with unittest.mock.patch.object(sg, "socket_path", return_value="/x/.socket2.sock"), \
                unittest.mock.patch.object(hyprbus, "connect", lambda names, direct=None: seen.append((names, direct))):
            sg.connect_events()
            sg.connect_events(("closewindow",))
        self.assertEqual(seen, [(sg.HYPR_EVENTS, "/x/.socket2.sock"), (("closewindow",), "/x/.socket2.sock")])


if __name__ == "__main__":
    unittest.main()
