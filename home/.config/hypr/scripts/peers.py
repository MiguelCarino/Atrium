#!/usr/bin/env python3
"""Machines: several of your computers as one desktop, peer to peer on the
local network -- never through anything in the cloud. Pair two machines once
with a code, then (each piece has its own switch, Settings > Machines):

    clipboard   a text copy here is on the other machine's clipboard too, and
                back (OFF as shipped: privacy.conf machines_clipboard)
    context     entering a project here (contexts.py) offers -- or, set to
                "auto", does -- the same on the other machine, when that one
                has the context or the repo at the same place under ~
    sessions    "send my windows" / "get its windows": the other side gets an
                offer with a Restore button (sessions.py), never a restore
    memory      ask the other machine's desktop memory from here (the launcher's
                "remember ..." items, the assistant's ask_machine tool);
                read-only, and only when THAT machine allows it (OFF as shipped:
                privacy.conf machines_memory)
    send        "send this window to the other machine": the page in the
                browser, the file in the editor / viewer / player, any file or
                link; it arrives in ~/Downloads (files) or as a notification
                with Open (links)
    kvm         one keyboard and mouse for both screens (lan-mouse, its own
                encrypted DTLS link; the fingerprints are swapped over the
                paired channel, so there is nothing to type)

    peers.py status [--json]          this machine, the paired ones, every switch
                                      (no network: for Settings)
    peers.py pair [--json] [--port N] show a code and wait for the other machine
                                      to join (3 minutes)
    peers.py join [HOST[:PORT]] [--json]   join a machine that shows a code (none
                                      given: the one found on the network)
    peers.py discover [--pairing] [--json] the machines announcing themselves (mDNS)
    peers.py unpair NAME              forget it (and tell it to forget this one)
    peers.py name NEW                 this machine's name, as the others show it
    peers.py set KEY VALUE            enabled on|off, context off|ask|auto,
                                      sessions on|off, send on|off, links ask|open,
                                      max_mb N, inbox PATH, port N
    peers.py clipboard on|off         share text copies (privacy.conf machines_clipboard)
    peers.py memory on|off            let paired machines ask this one's desktop
                                      memory (privacy.conf machines_memory)
    peers.py ping [NAME]              is it there, how fast, what it accepts
    peers.py send [--to NAME] FILE|URL...   send files / links
    peers.py send-window [--to NAME]  the focused window's page or file
    peers.py send-clipboard [--to NAME]   the clipboard's text, now (even with the
                                      automatic sharing off; never a secret)
    peers.py context [--to NAME] [CONTEXT]   tell it about the project you are
                                      in (or CONTEXT) now
    peers.py session send|get [--to NAME]   your windows to it / its windows here
                                      (an offer either way)
    peers.py recall [--to NAME] [--notify] [--json] QUESTION
                                      its desktop memory's answer
    peers.py kvm status|install|on|off|toggle   shared keyboard and mouse (lan-mouse)
    peers.py kvm side NAME left|right|top|bottom   where that machine's screen is
    peers.py serve                    the daemon (peers.service)
    peers.py clip-hook                (internal) wl-paste --watch runs it per copy

With more than one paired machine and no --to, a wofi list asks which.

SHIPS OFF. Nothing listens, announces itself or watches anything until a
machine is paired: pairing turns `enabled` on and starts peers.service;
forgetting the last one stops it again. `set enabled off` stops everything
while keeping the pairings.

WHO IS WHO. Each machine has an Ed25519 key and a self-signed certificate made
with it ($XDG_DATA_HOME/peers/identity.key, 0600, + identity.pem), made at the
first pairing. A machine's id is the SHA-256 of that certificate (shown as
AB12-CD34). Paired machines keep each other's certificate in peers.json.

PAIRING (pair_host / pair_join), inside a TLS 1.3 connection that is not yet
verified -- the code is what makes it verified:

    joiner -> host   its name, its certificate, commit = SHA-256(nJ)
    host -> joiner   its name, nH                (its certificate is the TLS one)
    joiner -> host   nJ, and a signature over the transcript with its key
    both             code = 6 digits of SHA-256("hypr-desktop-peers-sas-v1" | SHA-256(host
                     cert) | SHA-256(joiner cert) | nH | nJ), shown on both screens
    both             "the codes match" on BOTH machines -> each keeps the other's
                     certificate; either one saying no (or 3 minutes) -> nothing

The joiner commits to its nonce before it sees the host's, so someone in the
middle (who would have to show its own certificate to each side, and so
change the code) gets one blind try at making two codes agree: 1 in a
million, and the people looking at the codes notice. No code is typed, so
there is nothing to shoulder-surf; the comparison IS the check (Bluetooth's
numeric comparison, ZRTP's SAS).

ON THE WIRE, after pairing: mutual TLS 1.3 only. Each side's trust store is
exactly the paired certificates (pinned, no CA, no hostnames); a machine
that is not paired fails the handshake. One request per connection: a JSON
line, for a file its bytes after it, a JSON line back. Nothing travels in
plain text, the pairing included. Default port 47615/tcp (Fedora
Workstation's firewall zone allows 1025-65535 already).

FINDING EACH OTHER. mDNS through the system's avahi (avahi-publish /
avahi-browse, avahi-tools): _hyprdesk-peer._tcp while the daemon runs,
_hyprdesk-pair._tcp while a code is shown (a DNS-SD service name is 15
characters at most, hence not "hypr-desktop" in full), with the TXT id=, name=. Addresses
are also learnt from every connection either way and kept in
$XDG_DATA_HOME/peers/seen.json, so a machine that moved is found again.
The network is never scanned.

WHAT EACH SIDE ACCEPTS is decided on the RECEIVING side by its own switches:
a copy is put on the clipboard only where clipboard sharing is on there
too; a memory question is answered only where machines_memory is on there.

    clipboard   text only, at most 64 KB. Never sent: copies marked sensitive
                (password managers: CLIPBOARD_STATE), copies made in a private
                window / password manager / an app on Privacy's private list
                (smart-clipboard.py's private_focus), and anything
                desktop-memory.py's looks_secret() calls a secret (smart-
                clipboard's rules: keys, tokens, cards, IBANs, password-like
                words, "password: ..." lines, plus one-time codes). The
                receiver checks looks_secret() again. A copy that came from the
                other machine is not sent back (its digest is remembered).
    context     enter: the context with that name, else the one on the same
                repo; "ask" (as shipped) shows a notification with Enter, "auto"
                enters. When only the repo exists here, it asks to make a
                context for it. Leave: only a context entered because of the
                other machine, and only in "auto".
    sessions    the other machine's windows (sessions.py snapshot()), rebuilt
                for THIS machine before anything is kept: an app only by a
                .desktop entry that exists here (its file arguments only when
                they exist here), terminals only as a shell in the folder (when
                it exists here; nothing is run in them), mpv only on a file
                that exists here. Any other command line is dropped. Saved as
                the session "from NAME" (Settings > Workspace sessions has it
                too) and offered with Restore; never restored by itself.
    memory      desktop-memory.py recall on the answering machine (its local
                model); only the answer and its http(s) links come back, never
                the memories themselves. One question at a time.
    send        files into `inbox` (~/Downloads; at most max_mb, 500 MB as
                shipped), links as a notification with Open / Copy (links
                "open": opened at once). Folders and secret files (~/.ssh,
                *.env, key stores: llm-worker.py's rule) are not sent. A
                private browser window's page is not sent.

SHARED KEYBOARD AND MOUSE. lan-mouse 0.11.0 (github.com/feschber/lan-mouse,
GPL-3; not packaged for Fedora, no Flatpak): `kvm install` downloads the
release binary into $XDG_DATA_HOME/peers/lan-mouse/ and checks its SHA-256
(LANMOUSE_SHA256). It captures at the screen edge with layer-shell and
types with the wlroots virtual pointer / keyboard, both of which Hyprland
has. `kvm on` writes ~/.config/lan-mouse/config.toml from the pairings (the
other machines' lan-mouse certificate fingerprints, which this channel
carries, under [authorized_fingerprints]; each machine as a client on its
side) and starts lan-mouse.service. Setting a side here tells the other
machine the opposite one. lan-mouse's own release keys (default: hold
Ctrl+Shift+Super+Alt) bring the pointer back. input-leap 3.0.3 is packaged
(sudo dnf install input-leap) but needs the InputCapture portal, which
xdg-desktop-portal-hyprland does not have; Syncthing is not needed for any
of this (files go over the paired channel).

WHERE THINGS LIVE:

    ~/.config/hypr/peers.json        settings + the paired machines (their
                                     names, ids and public certificates)
    ~/.config/hypr/privacy.conf      machines_clipboard / machines_memory
                                     (privacy_settings.py; OFF as shipped)
    $XDG_DATA_HOME/peers/            identity.key / identity.pem, seen.json,
                                     lan-mouse/
    $XDG_RUNTIME_DIR/peers/          the last received copy's digest, which
                                     context was entered for which machine

TESTING. PEERS_HOME=DIR keeps everything above inside DIR (config, keys,
privacy.conf, lan-mouse's config), so two instances can run on one computer
(PEERS_BIND=127.0.0.1, different ports, PEERS_NO_MDNS=1); PEERS_SINK=1 (only
with PEERS_HOME) writes what would reach the desktop -- clipboard,
notifications, opened links, entered contexts, restore offers, memory
answers -- to DIR/effects.jsonl instead. tests/test_peers.py runs two such
instances over loopback end to end.

Logs say what happened and with whom ("copy from laptop, 31 characters",
"answered a memory question from laptop"), never what was copied or asked.
"""
import datetime
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import secrets
import select
import shutil
import signal
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request

try:
    from cryptography import x509
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519
    from cryptography.x509.oid import NameOID
except ImportError:         # status still answers; pairing says what to install
    x509 = None

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import privacy_settings  # noqa: E402

HOME = os.path.expanduser("~")
CONFIG_HOME = os.environ.get("XDG_CONFIG_HOME") or os.path.join(HOME, ".config")
DATA_HOME = os.environ.get("XDG_DATA_HOME") or os.path.join(HOME, ".local", "share")
TEST_HOME = os.environ.get("PEERS_HOME") or ""
CONF = os.path.join(TEST_HOME, "peers.json") if TEST_HOME else os.path.join(CONFIG_HOME, "hypr", "peers.json")
PRIVACY = os.path.join(TEST_HOME, "privacy.conf") if TEST_HOME else None    # None: privacy_settings.CONF
DATA = TEST_HOME or os.path.join(DATA_HOME, "peers")
RUN_DIR = os.path.join(TEST_HOME, "run") if TEST_HOME else \
    os.path.join(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}", "peers")
KEY = os.path.join(DATA, "identity.key")
CERT = os.path.join(DATA, "identity.pem")
SEEN = os.path.join(DATA, "seen.json")
LOCK = os.path.join(DATA, ".lock")
LAST_CLIP = os.path.join(RUN_DIR, "last-clip")
FOLLOWED = os.path.join(RUN_DIR, "followed.json")
SINK = bool(TEST_HOME and os.environ.get("PEERS_SINK"))
EFFECTS = os.path.join(TEST_HOME, "effects.jsonl")
BIND = os.environ.get("PEERS_BIND") or ""
NO_MDNS = bool(os.environ.get("PEERS_NO_MDNS"))

LANMOUSE_VERSION = "0.11.0"
LANMOUSE_URL = (f"https://github.com/feschber/lan-mouse/releases/download/v{LANMOUSE_VERSION}/"
                "lan-mouse-linux-x86_64")
LANMOUSE_SHA256 = "c43d211ec1af3eaea0cd585ac5c415776000355c3fcb9742fa2513f32dab55ba"
LANMOUSE = os.path.join(DATA_HOME, "peers", "lan-mouse", "lan-mouse")      # the binary: never per test home
LANMOUSE_CONF_DIR = os.path.join(TEST_HOME, "lan-mouse") if TEST_HOME else os.path.join(CONFIG_HOME, "lan-mouse")
LANMOUSE_CONF = os.path.join(LANMOUSE_CONF_DIR, "config.toml")
LANMOUSE_PEM = os.path.join(LANMOUSE_CONF_DIR, "lan-mouse.pem")
LANMOUSE_PORT = 4242
KVM_HEADER = "# Written by ~/.config/hypr/scripts/peers.py (Settings > Machines) from the paired machines.\n"

APP = "Machines"
ICON = "computer"
UNIT = "peers.service"
KVM_UNIT = "lan-mouse.service"
PORT = 47615
SERVICE = "_hyprdesk-peer._tcp"
PAIR_SERVICE = "_hyprdesk-pair._tcp"
PROTO = 1
SAS_LABEL = b"hypr-desktop-peers-sas-v1"
PAIR_TIMEOUT_S = 180
PAIR_TRIES = 3              # joins a shown code accepts (a failed handshake, a "no") before it ends
CONNECT_S = 3
MAX_LINE = 1 << 20          # one JSON message (a session is ~100 KB)
CLIP_MAX = 64 * 1024
MAX_WINDOWS = 200
RECALL_S = 150
HELLO_EVERY_S = 600
BROWSE_EVERY_S = 120
WATCH_S = 2
NAME_RE = re.compile(r"[\w][\w .'()-]{0,31}$")
URL_RE = re.compile(r"https?://[^\s]{1,4000}$")
SIDES = ("left", "right", "top", "bottom")
OPPOSITE = {"left": "right", "right": "left", "top": "bottom", "bottom": "top"}
DEFAULTS = {"enabled": False, "name": "", "port": PORT, "context": "ask", "sessions": True, "send": True,
            "links": "ask", "max_mb": 500, "inbox": "~/Downloads", "kvm": False, "peers": []}
CHOICES = {"enabled": ("on", "off"), "context": ("off", "ask", "auto"), "sessions": ("on", "off"),
           "send": ("on", "off"), "links": ("ask", "open"), "kvm": ("on", "off")}
BOOLS = ("enabled", "sessions", "send", "kvm")
MB = 1 << 20
TERM_DIR = {"kitty": ["kitty", "--directory"], "foot": ["foot", "-D"],
            "alacritty": ["alacritty", "--working-directory"], "wezterm": ["wezterm", "start", "--cwd"],
            "cosmic-term": ["cosmic-term", "--working-directory"], "ghostty": ["ghostty"]}
KEEP_FIELDS = ("class", "app", "title", "kind", "key", "pid", "workspace", "monitor", "rel", "size", "floating",
               "fullscreen", "fullscreen_client", "pinned")


class PeerError(Exception):
    """Something the user is told in one line (not reachable, refused...)."""


def log(text):
    print(f"peers: {text}", flush=True)


# -- other scripts, reused ----------------------------------------------------------------------
def _module(name, filename):
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return mod


def sessions_mod():
    import sessions
    return sessions


def contexts_mod():
    import contexts
    return contexts


def smartclip():
    return _module("smart_clipboard", "smart-clipboard.py")


def memory_mod():
    return _module("desktop_memory", "desktop-memory.py")


def phone_mod():
    return _module("phone", "phone.py")


def looks_secret(text):
    """desktop-memory.py's rule (smart-clipboard's + one-time codes). Unsure: secret."""
    try:
        return bool(memory_mod().looks_secret(text))
    except Exception:       # noqa: BLE001
        return True


def secret_path(path):
    try:
        return bool(smartclip().secret_path(path))
    except Exception:       # noqa: BLE001
        return True


# -- settings -------------------------------------------------------------------------------------
def default_name():
    return (socket.gethostname().split(".")[0] or "this computer")[:32]


def valid_name(name):
    return isinstance(name, str) and bool(NAME_RE.match(name)) and name.strip() == name


def load(path=None):
    try:
        with open(path or CONF) as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    conf = dict(DEFAULTS)
    for key, value in data.items():
        if key in DEFAULTS and (type(value) is type(DEFAULTS[key]) or key == "name" and isinstance(value, str)):
            conf[key] = value
    conf["peers"] = [tidy_peer(p) for p in conf["peers"] if isinstance(p, dict) and isinstance(p.get("id"), str)
                     and re.fullmatch(r"[0-9a-f]{64}", p["id"]) and isinstance(p.get("cert"), str)]
    if not valid_name(conf["name"]):
        conf["name"] = default_name()
    if conf["context"] not in CHOICES["context"]:
        conf["context"] = DEFAULTS["context"]
    if conf["links"] not in CHOICES["links"]:
        conf["links"] = DEFAULTS["links"]
    if not 1024 <= conf["port"] <= 65535:
        conf["port"] = PORT
    conf["max_mb"] = min(max(conf["max_mb"], 1), 20000)
    return conf


def tidy_peer(p):
    return {"id": p["id"], "name": p.get("name") if valid_name(p.get("name")) else p["id"][:8],
            "cert": p["cert"], "paired": p.get("paired") or 0,
            "kvm_side": p.get("kvm_side") if p.get("kvm_side") in SIDES else ""}


def write_json(path, data, mode=0o644):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w") as handle:
        json.dump(data, handle, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


class locked:
    """Across processes (the daemon, the CLI, the clipboard hook) and threads."""
    _thread = threading.RLock()

    def __enter__(self):
        self._thread.acquire()
        os.makedirs(DATA, exist_ok=True)
        self.fd = os.open(LOCK, os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(self.fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        fcntl.flock(self.fd, fcntl.LOCK_UN)
        os.close(self.fd)
        self._thread.release()


def update(change):
    """load, change(conf), save -- under the lock. Returns the new conf."""
    with locked():
        conf = load()
        change(conf)
        write_json(CONF, conf)
        return conf


def privacy():
    return privacy_settings.load(PRIVACY) if PRIVACY else privacy_settings.load()


def clipboard_on(pconf=None):
    return privacy_settings.machines_clipboard_on(privacy() if pconf is None else pconf)


def memory_on(pconf=None):
    return privacy_settings.machines_memory_on(privacy() if pconf is None else pconf)


def set_privacy(key, on):
    privacy_settings.set_key(key, "on" if on else "off", PRIVACY) if PRIVACY else \
        privacy_settings.set_key(key, "on" if on else "off")


def find_peer(conf, ref):
    """By id (or its first 4+ hex digits, dashes ignored) or by name."""
    if not ref:
        return None
    hexref = ref.replace("-", "").lower()
    for p in conf["peers"]:
        if p["id"] == hexref or p["name"].casefold() == ref.casefold():
            return p
    hits = [p for p in conf["peers"] if len(hexref) >= 4 and p["id"].startswith(hexref)]
    return hits[0] if len(hits) == 1 else None


def short_id(fp):
    return f"{fp[:4]}-{fp[4:8]}".upper() if fp else ""


# -- what was seen of each peer (addresses, when, what it accepts) ---------------------------------
def seen_all():
    try:
        with open(SEEN) as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def note_seen(pid, **fields):
    with locked():
        data = seen_all()
        rec = data.get(pid) if isinstance(data.get(pid), dict) else {}
        rec.update({k: v for k, v in fields.items() if v is not None})
        data[pid] = rec
        write_json(SEEN, data)
        return rec


def sender_fields(info, host=None):
    """What a peer's "from" says about itself, checked."""
    info = info if isinstance(info, dict) else {}
    port = info.get("port")
    kvm_fp = info.get("kvm_fp")
    return {"host": host,
            "port": port if isinstance(port, int) and 1024 <= port <= 65535 else None,
            "name": info.get("name") if valid_name(info.get("name")) else None,
            "kvm_fp": kvm_fp if isinstance(kvm_fp, str) and re.fullmatch(r"([0-9a-f]{2}:){31}[0-9a-f]{2}", kvm_fp)
            else None,
            "kvm_port": info.get("kvm_port") if isinstance(info.get("kvm_port"), int) else None}


# -- identity ---------------------------------------------------------------------------------
def need_crypto():
    if x509 is None:
        raise PeerError("python3-cryptography is missing (sudo dnf install python3-cryptography)")


def fingerprint(der):
    return hashlib.sha256(der).hexdigest()


def pem_to_der(pem):
    need_crypto()
    return x509.load_pem_x509_certificate(pem.encode()).public_bytes(serialization.Encoding.DER)


def der_to_pem(der):
    need_crypto()
    return x509.load_der_x509_certificate(der).public_bytes(serialization.Encoding.PEM).decode()


def make_identity(key_path=KEY, cert_path=CERT):
    """A new Ed25519 key (0600, never overwritten) and its self-signed
    certificate, valid for 100 years (the pin is the certificate itself)."""
    need_crypto()
    key = ed25519.Ed25519PrivateKey.generate()
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "hypr-desktop-peer")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=36500))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .sign(key, None))
    os.makedirs(os.path.dirname(key_path), mode=0o700, exist_ok=True)
    fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    with open(cert_path, "wb") as handle:
        handle.write(cert.public_bytes(serialization.Encoding.PEM))


def identity(create=True):
    """(certificate PEM, fingerprint), made on first use; (None, None) when
    there is none and create is False."""
    if not (os.path.exists(KEY) and os.path.exists(CERT)):
        if not create:
            return None, None
        if os.path.exists(KEY):     # a key without its certificate: never replace a key silently
            raise PeerError(f"{CERT} is missing but the key exists; move {KEY} away to make a new identity")
        make_identity()
    with open(CERT) as handle:
        pem = handle.read()
    return pem, fingerprint(pem_to_der(pem))


def private_key():
    need_crypto()
    with open(KEY, "rb") as handle:
        return serialization.load_pem_private_key(handle.read(), None)


def ed25519_public(pem):
    """The Ed25519 public key in a certificate, else PeerError."""
    need_crypto()
    try:
        key = x509.load_pem_x509_certificate(pem.encode()).public_key()
    except ValueError as exc:
        raise PeerError(f"not a certificate: {exc}") from None
    if not isinstance(key, ed25519.Ed25519PublicKey):
        raise PeerError("only Ed25519 certificates are accepted")
    return key


# -- TLS and the wire ------------------------------------------------------------------------
def tls_context(server, trust=None):
    """TLS 1.3 with this machine's certificate. trust: the PEMs accepted from
    the other side (pinned: they are the whole trust store); None only while
    pairing, where the code does the verifying."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER if server else ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    ctx.load_cert_chain(CERT, KEY)
    ctx.check_hostname = False
    if trust is None:
        ctx.verify_mode = ssl.CERT_NONE
    else:
        ctx.verify_mode = ssl.CERT_REQUIRED
        ctx.load_verify_locations(cadata="".join(trust))
    return ctx


class Wire:
    """JSON lines (and raw file bytes) over one TLS connection."""

    def __init__(self, sock):
        self.sock = sock
        self.f = sock.makefile("rwb")

    def send(self, obj):
        self.f.write(json.dumps(obj, ensure_ascii=False).encode() + b"\n")
        self.f.flush()

    def recv(self):
        line = self.f.readline(MAX_LINE + 1)
        if not line:
            raise PeerError("the connection closed")
        if not line.endswith(b"\n"):
            raise PeerError("a message too long")
        try:
            obj = json.loads(line)
        except ValueError:
            raise PeerError("a message that is not JSON") from None
        if not isinstance(obj, dict):
            raise PeerError("a message that is not an object")
        return obj

    def send_file(self, path):
        with open(path, "rb") as handle:
            shutil.copyfileobj(handle, self.f, 1 << 16)
        self.f.flush()

    def recv_file(self, size, out):
        left = size
        while left:
            chunk = self.f.read(min(left, 1 << 16))
            if not chunk:
                raise PeerError("the file stopped short")
            out.write(chunk)
            left -= len(chunk)

    def close(self):
        for thing in (self.f, self.sock):
            try:
                thing.close()
            except OSError:
                pass


def me_info(conf):
    return {"name": conf["name"], "port": conf["port"], "v": PROTO, "kvm_fp": kvm_fingerprint(),
            "kvm_port": LANMOUSE_PORT}


def addresses(peer, browse=True):
    """Where to try a peer: the last address it was seen at, then what mDNS says."""
    out = []
    rec = seen_all().get(peer["id"]) or {}
    if rec.get("host") and rec.get("port"):
        out.append((rec["host"], rec["port"]))
    if browse:
        for found in mdns_browse(SERVICE):
            if found.get("id") == peer["id"][:16] and (found["address"], found["port"]) not in out:
                out.append((found["address"], found["port"]))
                note_seen(peer["id"], host=found["address"], port=found["port"])
    return out


def connect(peer, timeout=CONNECT_S, browse=True):
    """(Wire, (host, port)) to a paired peer, its certificate checked twice:
    by the handshake (the only trusted one) and by its fingerprint."""
    ctx = tls_context(False, [peer["cert"]])
    tried = addresses(peer, browse=False)
    why = "never seen on the network"
    for attempt in (0, 1):
        for host, port in tried:
            try:
                raw = socket.create_connection((host, port), timeout=timeout)
            except OSError as exc:
                why = f"{host}:{port}: {exc.strerror or exc}"
                continue
            try:
                raw.settimeout(timeout + 5)
                tls = ctx.wrap_socket(raw)
                if fingerprint(tls.getpeercert(True)) != peer["id"]:
                    tls.close()
                    why = f"{host}:{port} is another machine"
                    continue
                return Wire(tls), (host, port)
            except (ssl.SSLError, OSError) as exc:
                raw.close()
                why = f"{host}:{port}: {getattr(exc, 'reason', None) or exc}"
        if attempt or not browse or NO_MDNS:
            break
        fresh = [a for a in addresses(peer, browse=True) if a not in tried]
        if not fresh:
            break
        tried = fresh
    raise PeerError(f"{peer['name']} is not reachable ({why})")


def request(peer, msg, conf=None, file=None, timeout=10, browse=True):
    """One request to a peer; its answer (a dict with "ok"). file: a path
    whose bytes follow the message."""
    conf = conf or load()
    wire, (host, port) = connect(peer, browse=browse)
    try:
        wire.sock.settimeout(timeout)
        wire.send(dict(msg, **{"from": me_info(conf)}))
        if file:
            wire.send_file(file)
        answer = wire.recv()
    except (OSError, ssl.SSLError) as exc:
        raise PeerError(f"{peer['name']}: {exc}") from None
    finally:
        wire.close()
    fields = sender_fields(answer.get("me"), host)
    fields["port"] = port
    note_seen(peer["id"], seen=time.time(), **fields)
    return answer


# -- mDNS (the system's avahi) ----------------------------------------------------------------
def mdns_publish(service, name, port, fp):
    """avahi-publish, alive while the returned process is; None without avahi."""
    if NO_MDNS or not shutil.which("avahi-publish"):
        return None
    argv = ["avahi-publish", "-s", f"{name} ({fp[:6]})", service, str(port),
            f"id={fp[:16]}", f"name={name}", f"v={PROTO}"]
    try:
        return subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return None


def avahi_unescape(text):
    return re.sub(r"\\(\d{3})", lambda m: chr(int(m[1])), text)


def parse_browse(out):
    """avahi-browse -prt lines -> [{"name", "id", "address", "port", "host"}],
    IPv4 first, link-local IPv6 left out (it needs an interface)."""
    found = {}
    for line in out.splitlines():
        parts = line.split(";")
        if len(parts) < 10 or parts[0] != "=":
            continue
        proto, address, port = parts[2], parts[7], parts[8]
        if proto == "IPv6" and address.lower().startswith("fe80"):
            continue
        txt = dict(t.strip('"').split("=", 1) for t in re.findall(r'"[^"]*"', ";".join(parts[9:])) if "=" in t)
        if not port.isdigit() or not re.fullmatch(r"[0-9a-f]{16}", txt.get("id", "")):
            continue
        rec = {"name": avahi_unescape(txt.get("name") or parts[3])[:32], "id": txt["id"], "address": address,
               "port": int(port), "host": parts[6]}
        key = (rec["id"], rec["port"])
        if key not in found or (proto == "IPv4" and ":" in found[key]["address"]):
            found[key] = rec
    return list(found.values())


def mdns_browse(service, timeout=6):
    if NO_MDNS or not shutil.which("avahi-browse"):
        return []
    try:
        out = subprocess.run(["avahi-browse", "-prt", service], capture_output=True, text=True,
                             timeout=timeout).stdout
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout.decode() if isinstance(exc.stdout, bytes) else exc.stdout or ""
    except OSError:
        return []
    return parse_browse(out)


def local_addresses():
    """This machine's LAN addresses, to show next to the code."""
    try:
        out = subprocess.run(["ip", "-4", "-o", "addr", "show", "scope", "global"], capture_output=True,
                             text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return re.findall(r"inet (\d+\.\d+\.\d+\.\d+)/", out)


# -- the desktop side (or the sink, in tests) ---------------------------------------------------
def effect(kind, **data):
    """In a test (PEERS_SINK) record what would reach the desktop; True then."""
    if not SINK:
        return False
    with locked():
        with open(EFFECTS, "a") as handle:
            handle.write(json.dumps(dict(data, kind=kind, t=time.time()), ensure_ascii=False) + "\n")
    return True


def notify(summary, body="", urgency="low", actions=(), timeout_ms=None):
    """A notification; with actions, waits and returns the key picked ("")."""
    if effect("notify", summary=summary, body=body, actions=[k for k, _ in actions]):
        return os.environ.get("PEERS_SINK_PICK", "")
    argv = ["notify-send", "-a", APP, "-i", ICON, "-u", urgency]
    if timeout_ms:
        argv += ["-t", str(timeout_ms)]
    for key, label in actions:
        argv.append(f"--action={key}={label}")
    if actions:
        argv.append("--wait")
    try:
        return subprocess.run(argv + ["--", summary, body], capture_output=True, text=True,
                              timeout=PAIR_TIMEOUT_S * 2 if actions else 10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def later(work, *args):
    threading.Thread(target=work, args=args, daemon=True).start()


def detach(argv):
    if effect("run", argv=[os.path.basename(a) if a.startswith(HOME) else a for a in argv]):
        return
    try:
        subprocess.Popen(argv, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def copy_text(text):
    """On the clipboard (text on stdin: argv is readable by every process);
    its digest kept so the hook does not send it back."""
    os.makedirs(RUN_DIR, mode=0o700, exist_ok=True)
    with open(LAST_CLIP, "w") as handle:
        handle.write(digest(text))
    if effect("copy", digest=digest(text), chars=len(text)):
        return
    try:
        subprocess.run(["wl-copy"], input=text.encode(), timeout=5, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        pass


def last_received():
    try:
        with open(LAST_CLIP) as handle:
            return handle.read().strip()
    except OSError:
        return ""


def open_target(target):
    detach(["xdg-open", target])


# -- what arrives (the daemon's side of each request) ------------------------------------------
def accepts(conf, pconf=None):
    pconf = privacy() if pconf is None else pconf
    return {"clipboard": clipboard_on(pconf), "context": conf["context"], "sessions": conf["sessions"],
            "send": conf["send"], "memory": memory_on(pconf)}


def op_hello(msg, peer, conf, wire):
    return {"ok": True, "accepts": accepts(conf), "v": PROTO}


def op_clip(msg, peer, conf, wire):
    text = msg.get("text")
    if not clipboard_on():
        return {"ok": False, "why": "clipboard sharing is off there"}
    if not isinstance(text, str) or not text or len(text.encode()) > CLIP_MAX or "\0" in text:
        return {"ok": False, "why": "not a text copy"}
    if looks_secret(text):
        return {"ok": False, "why": "looks like a secret"}
    copy_text(text)
    log(f"copy from {peer['name']}, {len(text)} characters")
    return {"ok": True}


def op_url(msg, peer, conf, wire):
    url = msg.get("url")
    if not conf["send"]:
        return {"ok": False, "why": "receiving is off there"}
    if not isinstance(url, str) or not URL_RE.match(url):
        return {"ok": False, "why": "not an http(s) link"}
    log(f"a link from {peer['name']}")
    if conf["links"] == "open":
        open_target(url)
        notify(f"Opened a link from {peer['name']}", url[:200])
    else:
        later(offer_url, peer["name"], url)
    return {"ok": True}


def offer_url(name, url):
    picked = notify(f"A link from {name}", url[:300], "normal", [("open", "Open"), ("copy", "Copy")], 120000)
    if picked == "open":
        open_target(url)
    elif picked == "copy":
        copy_text(url)


def clean_filename(name):
    name = os.path.basename(str(name or "").replace("\\", "/")).replace("\0", "").strip()
    name = name.lstrip(".") or "file"
    return name[:200]


def unique_path(folder, name):
    try:
        return phone_mod().unique_path(folder, name)
    except Exception:       # noqa: BLE001
        stem, ext = os.path.splitext(name)
        path, n = os.path.join(folder, name), 1
        while os.path.exists(path):
            n += 1
            path = os.path.join(folder, f"{stem} ({n}){ext}")
        return path


def op_file(msg, peer, conf, wire):
    size = msg.get("size")
    if not conf["send"]:
        return {"ok": False, "why": "receiving is off there"}
    if not isinstance(size, int) or size < 0 or size > conf["max_mb"] * MB:
        return {"ok": False, "why": f"bigger than {conf['max_mb']} MB, the limit there"}
    inbox = os.path.join(TEST_HOME, "inbox") if SINK else os.path.expanduser(conf["inbox"])
    os.makedirs(inbox, exist_ok=True)
    path = unique_path(inbox, clean_filename(msg.get("name")))
    part = os.path.join(inbox, f".{os.path.basename(path)}.part")
    wire.sock.settimeout(60)
    try:
        with open(part, "wb") as handle:
            wire.recv_file(size, handle)
        os.replace(part, path)
    except (OSError, PeerError):
        try:
            os.remove(part)
        except OSError:
            pass
        raise
    log(f"a file from {peer['name']}, {size} bytes")
    later(offer_file, peer["name"], path)
    return {"ok": True, "saved": os.path.basename(path)}


def offer_file(name, path):
    picked = notify(f"From {name}: {os.path.basename(path)}", f"saved in {short(os.path.dirname(path))}",
                    "normal", [("open", "Open"), ("folder", "Show in folder")], 120000)
    if picked == "open":
        open_target(path)
    elif picked == "folder":
        open_target(os.path.dirname(path))


def short(path):
    return "~" + path[len(HOME):] if path.startswith(HOME) else path


# -- sessions from another machine -------------------------------------------------------------
def local_launch(rec, index):
    """The record's launch rebuilt for this machine, or (None, why)."""
    launch = rec.get("launch") if isinstance(rec.get("launch"), dict) else {}
    did = launch.get("desktop")
    if isinstance(did, str) and did:
        entry = index["ids"].get(did.lower())
        if not entry:
            return None, f"{rec.get('app') or did} is not installed here"
        args = [a for a in launch.get("args") or [] if isinstance(a, str) and os.path.isabs(a)
                and os.path.exists(a) and not secret_path(a)]
        return {"desktop": entry["id"], "args": args[-1:]}, None
    argv = launch.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
        return None, "nothing to start"
    prog = os.path.basename(argv[0])
    if prog in TERM_DIR:
        if not shutil.which(prog):
            return None, f"{prog} is not installed here"
        cwd = launch.get("cwd") if isinstance(launch.get("cwd"), str) else ""
        cwd = cwd if cwd and os.path.isabs(cwd) and os.path.isdir(cwd) else HOME
        flag = TERM_DIR[prog]
        out = flag + [cwd] if prog != "ghostty" else flag + [f"--working-directory={cwd}"]
        return {"argv": out, "cwd": cwd}, None
    if prog == "mpv":
        path = argv[-1]
        if not (os.path.isabs(path) and os.path.isfile(path)) or secret_path(path):
            return None, "that video is not here"
        start = [a for a in argv[1:-1] if re.fullmatch(r"--start=\d+", a)]
        return {"argv": ["mpv"] + start[:1] + [path]}, None
    return None, f"{prog} is started by a command line, which is not taken from another machine"


def sanitize_session(data, index=None):
    """(records for THIS machine, [(app, why) dropped]) from a peer's snapshot."""
    windows = data.get("windows") if isinstance(data, dict) else None
    if not isinstance(windows, list):
        return [], []
    index = index or sessions_mod().desktop_index()
    keep, dropped = [], []
    for rec in windows[:MAX_WINDOWS]:
        if not isinstance(rec, dict):
            continue
        launch, why = local_launch(rec, index)
        if launch is None:
            dropped.append((str(rec.get("app") or rec.get("class") or "?")[:60], why))
            continue
        out = {k: rec[k] for k in KEEP_FIELDS if k in rec and isinstance(rec[k], (str, int, float, bool, list))
               and not isinstance(rec[k], dict)}
        out["launch"] = launch
        out["key"] = str(rec.get("key") or "")[:300]
        out["title"] = str(rec.get("title") or "")[:120]
        keep.append(out)
    return keep, dropped


def session_name(peer_name):
    return f"from {peer_name}"[:40]


def keep_and_offer(peer_name, data, wait=False):
    """Save a peer's windows as the session "from NAME" and offer it (in
    the daemon on a thread; wait: here, for a command that asked for it)."""
    records, dropped = sanitize_session(data)
    if not records:
        notify(f"{peer_name}'s windows", "none of them can be opened here"
               + (f" ({dropped[0][0]}: {dropped[0][1]})" if dropped else ""))
        return 0, len(dropped)
    s = sessions_mod()
    name = session_name(peer_name)
    saved = {"saved": time.time(), "instance": f"peer:{peer_name}", "windows": records,
             "skipped": [[a, w] for a, w in dropped], "from": peer_name}
    if SINK:
        effect("session", name=name, windows=len(records), dropped=len(dropped))
    else:
        s.write_json(s.session_path(name), saved)
    if wait:
        offer_session(peer_name, name, records, dropped)
    else:
        later(offer_session, peer_name, name, records, dropped)
    return len(records), len(dropped)


def offer_session(peer_name, name, records, dropped):
    apps = ", ".join(sorted({r.get("app") or r.get("class") or "?" for r in records}))[:200]
    body = f"{len(records)} window{'s' * (len(records) != 1)}: {apps}" + \
        (f"\n{len(dropped)} left out (not on this machine)" if dropped else "")
    picked = notify(f"Open {peer_name}'s windows here?", body, "normal",
                    [("restore", "Restore"), ("no", "Not now")], 120000)
    if picked == "restore":
        detach([sys.executable, os.path.join(HERE, "sessions.py"), "restore", name])


def op_session_offer(msg, peer, conf, wire):
    if not conf["sessions"]:
        return {"ok": False, "why": "sessions are off there"}
    count, dropped = keep_and_offer(peer["name"], msg.get("session"))
    log(f"windows offered by {peer['name']}: {count} kept, {dropped} left out")
    return {"ok": True, "windows": count, "dropped": dropped}


def my_session():
    data = sessions_mod().snapshot()
    return {"saved": data.get("saved") or time.time(), "windows": data.get("windows") or []}


def op_session_get(msg, peer, conf, wire):
    if not conf["sessions"]:
        return {"ok": False, "why": "sessions are off there"}
    log(f"{peer['name']} asked for the windows")
    return {"ok": True, "session": my_session()}


# -- project contexts ---------------------------------------------------------------------------
def tilde(path):
    path = os.path.abspath(os.path.expanduser(path))
    return "~" + path[len(HOME):] if path == HOME or path.startswith(HOME + "/") else path


def context_here(name, repo):
    """(the local context to enter or None, the repo path here when it exists)."""
    c = contexts_mod()
    contexts, _ = c.load()
    ctx = c.find(contexts, name) if c.valid_name(name) else None
    here = os.path.expanduser(repo) if isinstance(repo, str) and repo.startswith("~/") and ".." not in repo \
        else ""
    if ctx is None and here:
        ctx = next((x for x in contexts if os.path.abspath(c.repo_path(x)) == os.path.abspath(here)), None)
    return ctx, here if here and os.path.isdir(here) else ""


def followed():
    try:
        with open(FOLLOWED) as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def op_context(msg, peer, conf, wire):
    mode = conf["context"]
    if mode == "off":
        return {"ok": False, "why": "following projects is off there"}
    name, repo, action = msg.get("name"), msg.get("repo"), msg.get("action")
    if not isinstance(name, str) or len(name) > 40 or action not in ("enter", "leave"):
        return {"ok": False, "why": "not a context"}
    c = contexts_mod()
    current = c.state().get("name", "")
    script = os.path.join(HERE, "contexts.py")
    if action == "leave":
        f = followed()
        if mode == "auto" and current and current.casefold() == name.casefold() and f.get("name") == current:
            detach([sys.executable, script, "leave"])
            write_json(FOLLOWED, {})
            return {"ok": True, "did": "left"}
        return {"ok": True, "did": "nothing"}
    ctx, here = context_here(name, repo)
    if ctx and current.casefold() == ctx["name"].casefold():
        return {"ok": True, "did": "already in it"}
    if ctx:
        if mode == "auto":
            enter_for(peer["name"], ctx["name"], [sys.executable, script, "enter", ctx["name"]])
            return {"ok": True, "did": "entered"}
        later(offer_context, peer["name"], ctx["name"], [sys.executable, script, "enter", ctx["name"]],
              f"{peer['name']} is working on {name}")
        return {"ok": True, "did": "offered"}
    if here and c.valid_name(name):
        later(offer_context, peer["name"], name, [sys.executable, script, "new", name, "--repo", here, "--enter"],
              f"{peer['name']} is working on {name} ({tilde(here)}); it is not a project here yet")
        return {"ok": True, "did": "offered a new one"}
    return {"ok": True, "did": "nothing: no such project here"}


def enter_for(peer_name, name, argv):
    os.makedirs(RUN_DIR, mode=0o700, exist_ok=True)
    write_json(FOLLOWED, {"name": name, "peer": peer_name})
    detach(argv)


def offer_context(peer_name, name, argv, body):
    if notify(f"Work on {name} here too?", body, "normal", [("enter", "Enter"), ("no", "Not now")],
              60000) == "enter":
        enter_for(peer_name, name, argv)


# -- desktop memory ------------------------------------------------------------------------------
RECALL_LOCK = threading.Lock()


def recall_question(question):
    """The question as desktop-memory.py's argv: never a flag of its own."""
    return question.lstrip("-").strip() or "?"


def op_recall(msg, peer, conf, wire):
    question = msg.get("question")
    if not memory_on():
        return {"ok": False, "why": "that machine does not share its desktop memory (Settings > Machines there)"}
    if not isinstance(question, str) or not 3 <= len(question) <= 300:
        return {"ok": False, "why": "not a question"}
    if not RECALL_LOCK.acquire(blocking=False):
        return {"ok": False, "why": "it is answering another question; try again in a moment"}
    try:
        log(f"answered a memory question from {peer['name']}")
        if effect("recall", chars=len(question)):
            return {"ok": True, "answer": "(test) the memory would answer here", "links": []}
        wire.sock.settimeout(RECALL_S + 10)
        try:
            # desktop-memory.py takes no "--" (it would become part of the question) and
            # reads "--notify" anywhere as its flag: no leading dashes from the other side.
            out = subprocess.run([sys.executable, os.path.join(HERE, "desktop-memory.py"), "recall", "--json",
                                  recall_question(question)], capture_output=True, text=True,
                                 timeout=RECALL_S).stdout
            data = json.loads(out or "null") or {}
        except (OSError, subprocess.SubprocessError, ValueError):
            return {"ok": False, "why": "its desktop memory did not answer"}
        links = [u for u in data.get("links") or [] if isinstance(u, str) and URL_RE.match(u)]
        return {"ok": True, "answer": str(data.get("answer") or "")[:3000], "links": links[:6]}
    finally:
        RECALL_LOCK.release()


def op_kvm(msg, peer, conf, wire):
    side = msg.get("side")
    if side not in SIDES and side != "":
        return {"ok": False, "why": "not a side"}
    update(lambda c: [p.update(kvm_side=side) for p in c["peers"] if p["id"] == peer["id"]])
    if load()["kvm"]:
        write_kvm_config()
    return {"ok": True}


def op_unpair(msg, peer, conf, wire):
    forget(peer["id"])
    notify(f"{peer['name']} is no longer paired", "it forgot this machine; pair again to share with it",
           "normal")
    log(f"{peer['name']} unpaired")
    return {"ok": True}


OPS = {"hello": op_hello, "clip": op_clip, "url": op_url, "file": op_file, "session_offer": op_session_offer,
       "session_get": op_session_get, "context": op_context, "recall": op_recall, "kvm": op_kvm,
       "unpair": op_unpair}


def plain_address(host):
    """The dual-stack listener sees an IPv4 peer as ::ffff:a.b.c.d: keep the
    a.b.c.d (lan-mouse's IPv4 socket cannot reach the mapped form)."""
    return host[7:] if isinstance(host, str) and host.lower().startswith("::ffff:") and "." in host else host


def handle(conn, addr, ctx):
    """One connection to the daemon: the handshake (a paired certificate or
    nothing), one request, one answer."""
    conn.settimeout(5)          # short: an idle stranger must not hold one of the 8 slots for long
    try:
        tls = ctx.wrap_socket(conn, server_side=True)
    except (ssl.SSLError, OSError) as exc:
        log(f"refused a connection from {addr[0]}: {getattr(exc, 'reason', None) or exc}")
        conn.close()
        return
    tls.settimeout(15)
    wire = Wire(tls)
    try:
        conf = load()
        peer = next((p for p in conf["peers"] if p["id"] == fingerprint(tls.getpeercert(True))), None)
        if peer is None:
            return
        msg = wire.recv()
        fields = sender_fields(msg.get("from"), plain_address(addr[0]))
        note_seen(peer["id"], seen=time.time(), **fields)
        if fields["name"] and fields["name"] != peer["name"]:
            update(lambda c: [p.update(name=fields["name"]) for p in c["peers"] if p["id"] == peer["id"]])
            peer = dict(peer, name=fields["name"])
        fn = OPS.get(msg.get("op"))
        answer = fn(msg, peer, conf, wire) if fn else {"ok": False, "why": f"unknown request {msg.get('op')!r}"}
        wire.send(dict(answer, me=me_info(conf)))
    except (PeerError, OSError, ssl.SSLError) as exc:
        log(f"a request from {addr[0]} failed: {exc}")
    finally:
        wire.close()


# -- the daemon ----------------------------------------------------------------------------------
class Daemon:
    """peers.service: listen for paired machines, announce this one, and
    follow the clipboard and the project context while their switches are on."""

    def __init__(self):
        self.stop = threading.Event()
        self.conf = load()
        self.stamp = None
        self.ctx = None
        self.publisher = None
        self.published = None
        self.clip = None
        self.slots = threading.Semaphore(8)
        self.context = None
        self.last_browse = 0.0
        self.last_hello = 0.0

    def listen(self):
        port = self.conf["port"]
        if BIND:
            srv = socket.socket(socket.AF_INET6 if ":" in BIND else socket.AF_INET)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind((BIND, port))
        else:
            try:
                srv = socket.socket(socket.AF_INET6)
                srv.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
                srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                srv.bind(("::", port))
            except OSError:
                srv = socket.socket(socket.AF_INET)
                srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                srv.bind(("0.0.0.0", port))
        srv.listen(16)
        srv.settimeout(1)
        return srv

    def reload(self):
        """Re-read peers.json when it changed; False when the daemon should stop."""
        try:
            stamp = os.stat(CONF).st_mtime_ns
        except OSError:
            stamp = None
        if stamp == self.stamp and self.ctx is not None:
            return True
        self.stamp, self.conf = stamp, load()
        if not self.conf["enabled"] or not self.conf["peers"]:
            log("switched off or nothing paired: stopping")
            return False
        self.ctx = tls_context(True, [p["cert"] for p in self.conf["peers"]])
        _, fp = identity(create=False)
        if not fp:
            log(f"no identity in {DATA}: pair again")
            return False
        want = (self.conf["name"], self.conf["port"])
        if self.published != want:
            self.unpublish()
            self.publisher, self.published = mdns_publish(SERVICE, *want, fp), want
        if self.conf["kvm"]:
            write_kvm_config(self.conf)
        return True

    def unpublish(self):
        if self.publisher:
            self.publisher.terminate()
            try:
                self.publisher.wait(3)
            except subprocess.TimeoutExpired:
                self.publisher.kill()
        self.publisher = None

    def clipboard(self):
        """The wl-paste watcher, running exactly while clipboard sharing is on
        (never in a test home: it would read the real clipboard)."""
        want = clipboard_on() and not TEST_HOME and shutil.which("wl-paste")
        alive = self.clip is not None and self.clip.poll() is None
        if want and not alive:
            self.clip = subprocess.Popen(["wl-paste", "--type", "text", "--watch", sys.executable,
                                          os.path.abspath(__file__), "clip-hook"],
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif not want and alive:
            self.clip.terminate()
            self.clip = None

    def contexts(self):
        """Tell the peers when the project context here changes."""
        if self.conf["context"] == "off":
            self.context = None
            return
        try:
            now = contexts_mod().state()
        except Exception:       # noqa: BLE001
            return
        name = now.get("name", "")
        if self.context is None:
            self.context = name
            return
        if name == self.context:
            return
        before, self.context = self.context, name
        f = followed()
        if name:
            msg = {"op": "context", "action": "enter", "name": name, "repo": tilde(now.get("repo") or "")}
            skip = f.get("peer") if f.get("name") == name else None
        else:
            msg = {"op": "context", "action": "leave", "name": before}
            skip = f.get("peer") if f.get("name") == before else None
        if not name or f.get("name") != name:
            write_json(FOLLOWED, {})
        for peer in self.conf["peers"]:
            if peer["name"] != skip:
                later(quiet_request, peer, msg)

    def housekeeping(self, now):
        if now - self.last_browse > BROWSE_EVERY_S:
            self.last_browse = now
            ids = {p["id"][:16]: p["id"] for p in self.conf["peers"]}
            for found in mdns_browse(SERVICE):
                if found["id"] in ids:
                    note_seen(ids[found["id"]], host=found["address"], port=found["port"])
        if now - self.last_hello > HELLO_EVERY_S:
            self.last_hello = now
            for peer in self.conf["peers"]:
                later(quiet_request, peer, {"op": "hello"})

    def serve(self):
        os.makedirs(RUN_DIR, mode=0o700, exist_ok=True)
        if not self.reload():
            return 0
        try:
            srv = self.listen()
        except OSError as exc:
            log(f"cannot listen on port {self.conf['port']}: {exc}")
            return 1
        signal.signal(signal.SIGTERM, lambda *_: self.stop.set())
        signal.signal(signal.SIGINT, lambda *_: self.stop.set())
        log(f"{self.conf['name']} listening on {BIND or '*'}:{self.conf['port']}, "
            f"{len(self.conf['peers'])} paired")
        threading.Thread(target=self.accept, args=(srv,), daemon=True).start()
        try:
            while not self.stop.is_set():
                if not self.reload():
                    break
                self.clipboard()
                self.contexts()
                if self.conf["kvm"]:
                    # A peer's lan-mouse fingerprint / address arrives in seen.json (any
                    # request), not peers.json: rewrite on change; lan-mouse re-reads it.
                    write_kvm_config(self.conf)
                self.housekeeping(time.time())
                self.stop.wait(WATCH_S)
        finally:
            self.stop.set()
            srv.close()
            self.unpublish()
            if self.clip:
                self.clip.terminate()
        return 0

    def accept(self, srv):
        while not self.stop.is_set():
            try:
                conn, addr = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            if not self.slots.acquire(blocking=False):
                conn.close()
                continue
            threading.Thread(target=self.one, args=(conn, addr, self.ctx), daemon=True).start()

    def one(self, conn, addr, ctx):
        try:
            handle(conn, addr, ctx)
        finally:
            self.slots.release()


def quiet_request(peer, msg):
    try:
        return request(peer, msg, timeout=8, browse=False)
    except PeerError as exc:
        log(str(exc))
        return None


# -- pairing --------------------------------------------------------------------------------------
class UI:
    """How a pairing talks to the person: JSON lines on stdout and "yes"/"no"
    on stdin (Settings), a terminal prompt, or a notification with buttons."""

    def __init__(self, json_mode):
        self.json = json_mode

    def event(self, kind, **data):
        if self.json:
            print(json.dumps(dict(data, event=kind), ensure_ascii=False), flush=True)
        elif kind == "waiting":
            print(f"{data['name']} is waiting for the other machine (3 minutes). On it: Settings > Machines > "
                  f"Join, or `peers.py join {(data.get('addresses') or ['THIS-IP'])[0]}:{data['port']}`",
                  flush=True)
        elif kind == "code":
            print(f"\n    {data['code']}\n\nThe same code must be on {data['peer']}'s screen.", flush=True)
        else:
            print(f"{kind}: {data.get('peer') or data.get('why') or ''}".rstrip(": "), flush=True)

    def confirm(self, code, peer_name):
        self.event("code", code=code, peer=peer_name)
        if self.json:
            ready, _, _ = select.select([sys.stdin], [], [], PAIR_TIMEOUT_S)
            return bool(ready) and sys.stdin.readline().strip().lower() in ("yes", "y")
        if sys.stdin.isatty():
            try:
                return input("Do the codes match? [y/N] ").strip().lower() in ("y", "yes", "s", "si", "sí")
            except EOFError:
                return False
        return notify(f"Pair with {peer_name}?", f"Is this code on {peer_name} too?\n\n{code}", "critical",
                      [("yes", "The codes match"), ("no", "Cancel")]) == "yes"


def transcript(host_der, joiner_der, n_host, n_joiner):
    return SAS_LABEL + hashlib.sha256(host_der).digest() + hashlib.sha256(joiner_der).digest() + n_host + n_joiner


def sas(data):
    n = int.from_bytes(hashlib.sha256(data + b"|code").digest()[:8], "big") % 1_000_000
    return f"{n // 1000:03d} {n % 1000:03d}"


def add_peer(name, pem, host, port):
    fp = fingerprint(pem_to_der(pem))

    def change(conf):
        conf["peers"] = [p for p in conf["peers"] if p["id"] != fp]
        conf["peers"].append({"id": fp, "name": name, "cert": pem, "paired": int(time.time()), "kvm_side": ""})
        conf["enabled"] = True
    update(change)
    note_seen(fp, host=host, port=port, seen=time.time(), name=name)
    systemctl("enable", "--now", UNIT)     # already running: it re-reads peers.json by itself
    return fp


def check_name(name):
    if not valid_name(name):
        raise PeerError("the other machine sent a name that is not one")
    return name


def pair_host(ui, port=0):
    """Show a code and wait for a joiner: "paired", "rejected" or "timeout"."""
    need_crypto()
    _, fp = identity()
    conf = load()
    ctx = tls_context(True, None)
    srv = socket.socket(socket.AF_INET6 if ":" in BIND else socket.AF_INET)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((BIND or "0.0.0.0", port))
    srv.listen(2)
    port = srv.getsockname()[1]
    publisher = mdns_publish(PAIR_SERVICE, conf["name"], port, fp)
    ui.event("waiting", name=conf["name"], id=short_id(fp), port=port, addresses=local_addresses())
    deadline = time.monotonic() + PAIR_TIMEOUT_S
    try:
        for _ in range(PAIR_TRIES):
            srv.settimeout(max(deadline - time.monotonic(), 0.1))
            try:
                conn, addr = srv.accept()
            except socket.timeout:
                ui.event("timeout", why="nobody joined in time")
                return "timeout"
            try:
                result = host_session(conn, addr, ctx, conf, ui)
            except (PeerError, OSError, ssl.SSLError, ValueError) as exc:
                ui.event("error", why=str(exc))
                continue
            finally:
                conn.close()
            return result
        return "rejected"
    finally:
        srv.close()
        if publisher:
            publisher.terminate()


def host_session(conn, addr, ctx, conf, ui):
    conn.settimeout(20)
    tls = ctx.wrap_socket(conn, server_side=True)
    wire = Wire(tls)
    m1 = wire.recv()
    if m1.get("op") != "pair" or m1.get("v") != PROTO:
        raise PeerError("not a pairing request (or another version)")
    name = check_name(m1.get("name"))
    pem = m1.get("cert") if isinstance(m1.get("cert"), str) else ""
    key = ed25519_public(pem)
    joiner_der = pem_to_der(pem)
    commit = m1.get("commit")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{64}", commit):
        raise PeerError("no commitment")
    if fingerprint(joiner_der) == fingerprint(pem_to_der(identity()[0])):
        raise PeerError("that is this machine")
    n_host = secrets.token_bytes(32)
    wire.send({"name": conf["name"], "nonce": n_host.hex(), "port": conf["port"]})
    m2 = wire.recv()
    try:
        n_joiner = bytes.fromhex(m2.get("nonce") or "")
        sig = bytes.fromhex(m2.get("sig") or "")
    except (TypeError, ValueError):
        raise PeerError("a broken answer") from None
    if len(n_joiner) != 32 or hashlib.sha256(n_joiner).hexdigest() != commit:
        raise PeerError("its nonce does not match what it committed to")
    data = transcript(pem_to_der(identity()[0]), joiner_der, n_host, n_joiner)
    try:
        key.verify(sig, data)
    except InvalidSignature:
        raise PeerError("its signature does not hold") from None
    return decide(wire, ui, sas(data), name, pem, addr[0], m1.get("port"))


def decide(wire, ui, code, name, pem, host, port):
    """Both people say whether the codes match; paired only when both do."""
    ok = ui.confirm(code, name)
    wire.sock.settimeout(PAIR_TIMEOUT_S)
    wire.send({"ok": ok})
    theirs = wire.recv().get("ok") is True
    if ok and theirs:
        add_peer(name, pem, host, port if isinstance(port, int) and 1024 <= port <= 65535 else PORT)
        ui.event("paired", peer=name)
        notify(f"Paired with {name}", "Settings > Machines has what is shared with it")
        return "paired"
    ui.event("rejected", why="the codes were not confirmed on " + ("this machine" if not ok else name))
    return "rejected"


def pair_join(ui, target=None):
    """Join a machine that shows a code: "paired" or "rejected"."""
    need_crypto()
    my_pem, my_fp = identity()
    conf = load()
    if target:
        host, _, port = target.rpartition(":") if target.count(":") == 1 or target.startswith("[") \
            else (target, "", "")
        host = host.strip("[]") or target
        if not port.isdigit():
            raise PeerError("give the address with its port: HOST:PORT (both are next to the code)")
        port = int(port)
    else:
        found = [f for f in mdns_browse(PAIR_SERVICE) if f["id"] != my_fp[:16]]
        if not found:
            raise PeerError("no machine is showing a code on this network (Pair new there first)")
        if len(found) > 1:
            raise PeerError("several machines show a code: " + ", ".join(f"{f['name']} ({f['address']}:"
                                                                         f"{f['port']})" for f in found))
        host, port = found[0]["address"], found[0]["port"]
    ctx = tls_context(False, None)
    raw = socket.create_connection((host, port), timeout=CONNECT_S + 2)
    raw.settimeout(20)
    tls = ctx.wrap_socket(raw)
    wire = Wire(tls)
    try:
        host_der = tls.getpeercert(True)
        host_pem = der_to_pem(host_der)
        ed25519_public(host_pem)
        if fingerprint(host_der) == my_fp:
            raise PeerError("that is this machine")
        n_joiner = secrets.token_bytes(32)
        wire.send({"op": "pair", "v": PROTO, "name": conf["name"], "cert": my_pem,
                   "commit": hashlib.sha256(n_joiner).hexdigest(), "port": conf["port"]})
        m = wire.recv()
        name = check_name(m.get("name"))
        try:
            n_host = bytes.fromhex(m.get("nonce") or "")
        except (TypeError, ValueError):
            raise PeerError("a broken answer") from None
        if len(n_host) != 32:
            raise PeerError("a broken answer")
        data = transcript(host_der, pem_to_der(my_pem), n_host, n_joiner)
        wire.send({"nonce": n_joiner.hex(), "sig": private_key().sign(data).hex()})
        return decide(wire, ui, sas(data), name, host_pem, host, m.get("port"))
    finally:
        wire.close()


# -- leaving -----------------------------------------------------------------------------------
def systemctl(*args):
    if TEST_HOME:
        effect("systemctl", args=list(args))
        return True
    try:
        return subprocess.run(["systemctl", "--user", *args], capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def forget(pid):
    """Drop a peer here; the last one gone turns the whole thing (and the
    shared keyboard) off."""
    conf = update(lambda c: c.update(peers=[p for p in c["peers"] if p["id"] != pid]))
    with locked():
        data = seen_all()
        data.pop(pid, None)
        write_json(SEEN, data)
    if not conf["peers"]:
        update(lambda c: c.update(enabled=False, kvm=False))
        systemctl("disable", "--now", KVM_UNIT)
        systemctl("disable", UNIT)          # a running daemon sees no peers and stops by itself
    elif conf["kvm"]:
        write_kvm_config(conf)


def unpair(ref):
    conf = load()
    peer = find_peer(conf, ref)
    if not peer:
        raise PeerError(f"no paired machine called {ref!r} (peers.py status)")
    told = True
    try:
        request(peer, {"op": "unpair"}, conf, timeout=5, browse=False)
    except PeerError:
        told = False
    forget(peer["id"])
    return f"forgot {peer['name']}" + ("" if told else " (it was not reachable: forget this machine there too)")


# -- sending ------------------------------------------------------------------------------------
def choose(conf, to=None, ask=True):
    """The peer meant: --to, the only one, or a wofi pick (ask=False: the
    one seen last, for callers with nobody to ask -- the assistant)."""
    if not conf["peers"]:
        raise PeerError("no machine is paired (Settings > Machines > Pair new)")
    if to:
        peer = find_peer(conf, to)
        if not peer:
            raise PeerError(f"no paired machine called {to!r}")
        return peer
    if len(conf["peers"]) == 1:
        return conf["peers"][0]
    seen = seen_all()
    peers = sorted(conf["peers"], key=lambda p: -(seen.get(p["id"]) or {}).get("seen", 0))
    if SINK or not ask or not shutil.which("wofi"):
        return peers[0]
    try:
        out = subprocess.run(["wofi", "--dmenu", "--prompt", "Which machine?", "--lines", str(len(peers) + 1)],
                             input="\n".join(p["name"] for p in peers), capture_output=True, text=True,
                             timeout=120).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        out = ""
    peer = find_peer(conf, out)
    if not peer:
        raise PeerError("no machine picked")
    return peer


def send_targets(peer, targets, conf=None):
    """Files and links to a peer; [(target, answer or why)]."""
    conf = conf or load()
    out = []
    for target in targets:
        try:
            if URL_RE.match(target):
                answer = request(peer, {"op": "url", "url": target}, conf)
            elif os.path.isdir(target):
                raise PeerError("folders are not sent (zip it, or send the files)")
            elif not os.path.isfile(target):
                raise PeerError("no such file")
            elif secret_path(os.path.abspath(target)):
                raise PeerError("that file holds keys or secrets: not sent")
            else:
                size = os.path.getsize(target)
                answer = request(peer, {"op": "file", "name": os.path.basename(target), "size": size}, conf,
                                 file=target, timeout=max(30, size // MB))
            out.append((target, answer.get("why") if not answer.get("ok") else None))
        except (PeerError, OSError) as exc:
            out.append((target, str(exc)))
    return out


def window_target(client):
    """(the URL or file the window shows, None) or (None, why)."""
    if not isinstance(client, dict) or not client.get("class"):
        return None, "no window has the focus"
    try:
        if smartclip().private_focus(window=client):
            return None, "that is a private window: nothing from it is sent"
    except Exception:       # noqa: BLE001
        return None, "could not tell whether that window is private"
    s = sessions_mod()
    cls, title = client.get("class") or "", client.get("title") or ""
    if s.BROWSER_RE.search(cls):
        m = re.search(r"https?://\S+", title)
        if m:
            return m[0], None
        ph = phone_mod()
        url = ph.url_from_sessions(cls, ph.page_title(title))
        return (url, None) if url else (None, "could not find that page's address in the browser's session "
                                              "file yet (copy it, then send the clipboard)")
    rec, why = s.capture(client, private=s.private_classes())
    if rec and rec.get("kind") == "terminal":
        return None, "a terminal has no file to send: copy the text and send the clipboard"
    launch = (rec or {}).get("launch") or {}
    paths = [a for a in (launch.get("args") or launch.get("argv") or [])[1 if launch.get("argv") else 0:]
             if isinstance(a, str) and os.path.isabs(a)]
    if not paths and client.get("pid"):
        paths = s.path_args(s.cmdline(client["pid"]))
    files = [p for p in paths if os.path.isfile(p)]
    if files:
        return os.path.abspath(files[-1]), None
    if paths and os.path.isdir(paths[-1]):
        return None, "that window shows a folder: folders are not sent"
    return None, f"{rec.get('app') if rec else cls} shows no file this can find" + (f" ({why})" if why else "")


def active_window():
    try:
        out = subprocess.run(["hyprctl", "activewindow", "-j"], capture_output=True, text=True, timeout=3).stdout
        return json.loads(out or "null")
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def say_sent(peer, results):
    good = [os.path.basename(t) if not URL_RE.match(t) else t for t, why in results if not why]
    bad = [f"{os.path.basename(t)}: {why}" for t, why in results if why]
    if good:
        notify(f"Sent to {peer['name']}", ", ".join(good)[:300])
    if bad:
        notify(f"Not sent to {peer['name']}", "\n".join(bad)[:400], "normal")
    return 0 if good and not bad else 1


def clip_hook(stdin=None, env=None):
    """One copy (wl-paste --watch): to every peer, unless a rule says no."""
    env = os.environ if env is None else env
    if env.get("CLIPBOARD_STATE", "data") != "data":
        return "sensitive"
    conf = load()
    if not conf["enabled"] or not conf["peers"] or not clipboard_on():
        return "off"
    try:
        if smartclip()._watcher_age() < smartclip().STARTUP_S:
            return "startup"
    except Exception:       # noqa: BLE001
        pass
    raw = (stdin or sys.stdin.buffer).read(CLIP_MAX + 1)
    if not raw or len(raw) > CLIP_MAX or b"\0" in raw:
        return "not text"
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return "not text"
    if not text.strip():
        return "empty"
    if digest(text) == last_received():
        return "came from a peer"
    if looks_secret(text):
        return "secret"
    try:
        if smartclip().private_focus():
            return "private window"
    except Exception:       # noqa: BLE001
        return "private window"
    threads = [threading.Thread(target=quiet_request, args=(p, {"op": "clip", "text": text})) for p in conf["peers"]]
    for t in threads:
        t.start()
    for t in threads:
        t.join(12)
    return "sent"


def send_clipboard(peer):
    try:
        text = subprocess.run(["wl-paste", "--no-newline", "--type", "text"], capture_output=True, timeout=3)
        types = subprocess.run(["wl-paste", "--list-types"], capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        raise PeerError("could not read the clipboard") from None
    if phone_mod().SECRET_TYPE in types.split():
        raise PeerError("a password manager copied that: not sent")
    try:
        body = text.stdout.decode("utf-8")
    except UnicodeDecodeError:
        raise PeerError("the clipboard holds no text") from None
    if not body.strip():
        raise PeerError("the clipboard holds no text")
    if looks_secret(body):
        raise PeerError("that looks like a secret: not sent")
    if URL_RE.match(body.strip()):
        return say_sent(peer, send_targets(peer, [body.strip()]))
    answer = request(peer, {"op": "clip", "text": body[:CLIP_MAX]})
    if not answer.get("ok"):
        raise PeerError(answer.get("why") or "refused")
    notify(f"On {peer['name']}'s clipboard", f"{len(body)} characters")
    return 0


# -- sessions, contexts, memory: the asking side ------------------------------------------------
def session_cmd(action, peer):
    conf = load()
    if action == "send":
        data = my_session()
        if not data["windows"]:
            raise PeerError("no windows to send")
        answer = request(peer, {"op": "session_offer", "session": data}, conf, timeout=20)
        if not answer.get("ok"):
            raise PeerError(answer.get("why") or "refused")
        notify(f"Offered your windows to {peer['name']}",
               f"{answer.get('windows', 0)} can open there" +
               (f", {answer['dropped']} cannot" if answer.get("dropped") else ""))
        return 0
    answer = request(peer, {"op": "session_get"}, conf, timeout=20)
    if not answer.get("ok"):
        raise PeerError(answer.get("why") or "refused")
    if not conf["sessions"]:
        raise PeerError("sessions are off on this machine (Settings > Machines)")
    keep_and_offer(peer["name"], answer.get("session"), wait=True)
    return 0


def context_cmd(peers, name=None):
    c = contexts_mod()
    if name:
        contexts, _ = c.load()
        ctx = c.find(contexts, name)
        if not ctx:
            raise PeerError(f"no context called {name!r} here")
        cur = {"name": ctx["name"], "repo": ctx["repo"]}
    else:
        cur = c.state()
        if not cur.get("name"):
            raise PeerError("you are in no project context now")
    msg = {"op": "context", "action": "enter", "name": cur["name"], "repo": tilde(cur.get("repo") or "")}
    lines = []
    for peer in peers:
        try:
            answer = request(peer, msg)
            lines.append(f"{peer['name']}: {answer.get('did') or answer.get('why')}")
        except PeerError as exc:
            lines.append(str(exc))
    return lines


def recall(peer, question):
    answer = request(peer, {"op": "recall", "question": question}, timeout=RECALL_S + 15)
    if not answer.get("ok"):
        raise PeerError(answer.get("why") or "refused")
    return answer


def notify_recall(peer, question):
    notify(f"Asking {peer['name']}'s memory…", question)
    try:
        answer = recall(peer, question)
    except PeerError as exc:
        notify(f"{peer['name']} did not answer", str(exc), "normal")
        return 1
    links = answer.get("links") or []
    picked = notify(f"{peer['name']} remembers", answer.get("answer") or "(no answer)", "normal",
                    [(f"open{i}", urllib.parse.urlparse(u).netloc or u[:30]) for i, u in enumerate(links[:3])],
                    60000)
    if picked.startswith("open") and picked[4:].isdigit() and int(picked[4:]) < len(links):
        open_target(links[int(picked[4:])])
    return 0


# -- shared keyboard and mouse (lan-mouse) ------------------------------------------------------------
def kvm_installed():
    return os.path.isfile(LANMOUSE) and os.access(LANMOUSE, os.X_OK)


def kvm_fingerprint(path=None):
    """lan-mouse's certificate fingerprint, as it shows them (aa:bb:...), from
    the PEM it writes at its first start; None before that."""
    try:
        with open(path or LANMOUSE_PEM) as handle:
            text = handle.read()
    except OSError:
        return None
    m = re.search(r"-----BEGIN CERTIFICATE-----(.+?)-----END CERTIFICATE-----", text, re.S)
    if not m:
        return None
    import base64
    try:
        der = base64.b64decode("".join(m[1].split()))
    except ValueError:
        return None
    return ":".join(f"{b:02x}" for b in hashlib.sha256(der).digest())


def toml_str(text):
    return json.dumps(str(text), ensure_ascii=False)


def kvm_config(conf, seen):
    """config.toml for lan-mouse: the paired machines' fingerprints and, for
    each with a side and an address, a client there."""
    lines = [KVM_HEADER, f"port = {LANMOUSE_PORT}", "", "[authorized_fingerprints]"]
    for p in conf["peers"]:
        fp = (seen.get(p["id"]) or {}).get("kvm_fp")
        if fp:
            lines.append(f"{toml_str(fp)} = {toml_str(p['name'])}")
    for p in conf["peers"]:
        rec = seen.get(p["id"]) or {}
        if p["kvm_side"] in SIDES and rec.get("host"):
            lines += ["", "[[clients]]", f"position = {toml_str(p['kvm_side'])}",
                      f"ips = [{toml_str(rec['host'])}]",
                      f"port = {int(rec.get('kvm_port') or LANMOUSE_PORT)}", "activate_on_startup = true"]
    return "\n".join(lines) + "\n"


def write_kvm_config(conf=None):
    """Write it when it changed (lan-mouse re-reads it by itself); a config
    that is not ours is moved aside first, once."""
    text = kvm_config(conf or load(), seen_all())
    try:
        with open(LANMOUSE_CONF) as handle:
            old = handle.read()
    except OSError:
        old = None
    if old == text:
        return False
    os.makedirs(LANMOUSE_CONF_DIR, exist_ok=True)
    if old is not None and not old.startswith(KVM_HEADER):
        os.replace(LANMOUSE_CONF, LANMOUSE_CONF + ".before-peers")
    tmp = LANMOUSE_CONF + ".tmp"
    with open(tmp, "w") as handle:
        handle.write(text)
    os.replace(tmp, LANMOUSE_CONF)
    return True


def kvm_install():
    """The pinned lan-mouse release, checked against LANMOUSE_SHA256."""
    if kvm_installed():
        return f"lan-mouse is installed ({LANMOUSE})"
    os.makedirs(os.path.dirname(LANMOUSE), exist_ok=True)
    part = LANMOUSE + ".part"
    sha = hashlib.sha256()
    try:
        with urllib.request.urlopen(LANMOUSE_URL, timeout=60) as resp, open(part, "wb") as out:
            while chunk := resp.read(1 << 16):
                sha.update(chunk)
                out.write(chunk)
    except OSError as exc:
        raise PeerError(f"the download failed: {exc}") from None
    if sha.hexdigest() != LANMOUSE_SHA256:
        os.remove(part)
        raise PeerError("the download is not the expected lan-mouse release (checksum): removed")
    os.chmod(part, 0o755)
    os.replace(part, LANMOUSE)
    return f"lan-mouse {LANMOUSE_VERSION} installed ({LANMOUSE})"


def kvm_set(on):
    conf = load()
    if on:
        if not conf["peers"]:
            raise PeerError("pair a machine first")
        if not conf["enabled"]:
            raise PeerError("sharing with the paired machines is off (Settings > Machines)")
        if not kvm_installed():
            raise PeerError("lan-mouse is not installed (peers.py kvm install, or the Install button)")
        if not any(p["kvm_side"] for p in conf["peers"]):
            kvm_side(conf["peers"][0]["id"], "right")      # tells it: this machine is on its left
        conf = update(lambda c: c.update(kvm=True))
        write_kvm_config(conf)
        if not systemctl("enable", "--now", KVM_UNIT):
            update(lambda c: c.update(kvm=False))
            raise PeerError("lan-mouse.service did not start (journalctl --user -u lan-mouse)")
        for peer in conf["peers"]:          # they learn this machine's lan-mouse fingerprint
            later(quiet_request, peer, {"op": "hello"})
        return "shared keyboard and mouse on"
    update(lambda c: c.update(kvm=False))
    systemctl("disable", "--now", KVM_UNIT)
    return "shared keyboard and mouse off"


def kvm_side(ref, side):
    conf = load()
    peer = find_peer(conf, ref)
    if not peer:
        raise PeerError(f"no paired machine called {ref!r}")
    if side not in SIDES:
        raise PeerError("the side is left, right, top or bottom")
    conf = update(lambda c: [p.update(kvm_side=side) for p in c["peers"] if p["id"] == peer["id"]])
    if conf["kvm"]:
        write_kvm_config(conf)
    try:
        request(peer, {"op": "kvm", "side": OPPOSITE[side]}, conf, timeout=5)
        return f"{peer['name']} is to the {side}; it has this machine to the {OPPOSITE[side]}"
    except PeerError:
        return f"{peer['name']} is to the {side} (it was not reachable: set the other side there too)"


def kvm_status(conf=None):
    conf = conf or load()
    # The binary is never run for this: even `lan-mouse --version` writes an
    # empty ~/.config/lan-mouse/config.toml. Its version is the pinned one
    # (install checks the SHA-256).
    version = LANMOUSE_VERSION if kvm_installed() else None
    return {"on": conf["kvm"], "installed": kvm_installed(), "version": version, "path": LANMOUSE,
            "service": unit_state(KVM_UNIT), "fingerprint": kvm_fingerprint(), "config": LANMOUSE_CONF,
            "pinned": LANMOUSE_VERSION}


# -- status ---------------------------------------------------------------------------------------
def unit_state(unit):
    if TEST_HOME:
        return "test"
    try:
        active = subprocess.run(["systemctl", "--user", "is-active", unit], capture_output=True, text=True,
                                timeout=5).stdout.strip()
        enabled = subprocess.run(["systemctl", "--user", "is-enabled", unit], capture_output=True, text=True,
                                 timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return f"{active}, {enabled}"


def status():
    conf = load()
    pconf = privacy()
    seen = seen_all()
    _, fp = identity(create=False) if x509 is not None else (None, None)
    peers = []
    for p in conf["peers"]:
        rec = seen.get(p["id"]) or {}
        peers.append({"id": p["id"], "short": short_id(p["id"]), "name": p["name"], "paired": p["paired"],
                      "kvm_side": p["kvm_side"], "host": rec.get("host"), "port": rec.get("port"),
                      "seen": rec.get("seen"), "kvm_fp": bool(rec.get("kvm_fp"))})
    return {"name": conf["name"], "id": short_id(fp) if fp else None, "enabled": conf["enabled"],
            "port": conf["port"], "service": unit_state(UNIT), "peers": peers,
            "features": {"clipboard": clipboard_on(pconf), "context": conf["context"],
                         "sessions": conf["sessions"], "send": conf["send"], "links": conf["links"],
                         "memory": memory_on(pconf), "max_mb": conf["max_mb"], "inbox": conf["inbox"]},
            "kvm": kvm_status(conf), "mdns": bool(shutil.which("avahi-browse")) and not NO_MDNS,
            "crypto": x509 is not None, "addresses": local_addresses(), "conf": CONF}


def human_status(data):
    lines = [f"this machine  {data['name']} ({data['id'] or 'no identity yet'}), port {data['port']}, "
             f"{'on' if data['enabled'] else 'off'}, peers.service {data['service']}"]
    for p in data["peers"]:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(p["seen"])) if p.get("seen") else "never"
        lines.append(f"paired       {p['name']} ({p['short']}), last seen {when}"
                     + (f" at {p['host']}:{p['port']}" if p.get("host") else ""))
    if not data["peers"]:
        lines.append("paired       none (peers.py pair, then peers.py join on the other machine)")
    f = data["features"]
    lines.append("sharing      " + ", ".join(f"{k} {('on' if v else 'off') if isinstance(v, bool) else v}"
                                            for k, v in f.items() if k not in ("inbox",)))
    k = data["kvm"]
    lines.append(f"keyboard     lan-mouse {'installed ' + (k['version'] or '') if k['installed'] else 'not installed'}"
                 f", {'on' if k['on'] else 'off'}, {k['service']}")
    return "\n".join(lines)


def set_option(key, value):
    if key in BOOLS and key != "kvm":
        if value not in ("on", "off"):
            raise PeerError(f"{key} is on or off")
        if key == "enabled":
            if value == "on" and not load()["peers"]:
                raise PeerError("pair a machine first: it switches on by itself then")
            conf = update(lambda c: c.update(enabled=value == "on"))
            if value == "on":
                systemctl("enable", "--now", UNIT)
                if conf["kvm"] and kvm_installed():         # the shared keyboard comes back with it
                    systemctl("enable", "--now", KVM_UNIT)
            else:                                           # everything stops; the kvm switch is kept
                systemctl("disable", "--now", UNIT)
                systemctl("disable", "--now", KVM_UNIT)
            return
        update(lambda c: c.update({key: value == "on"}))
    elif key in ("context", "links"):
        if value not in CHOICES[key]:
            raise PeerError(f"{key} is one of {', '.join(CHOICES[key])}")
        update(lambda c: c.update({key: value}))
    elif key in ("max_mb", "port"):
        lo, hi = (1, 20000) if key == "max_mb" else (1024, 65535)
        if not value.isdigit() or not lo <= int(value) <= hi:
            raise PeerError(f"{key} is a number from {lo} to {hi}")
        update(lambda c: c.update({key: int(value)}))
        if key == "port":
            systemctl("try-restart", UNIT)
    elif key == "inbox":
        path = os.path.expanduser(value)
        if not os.path.isabs(path):
            raise PeerError("the inbox is a folder path")
        update(lambda c: c.update(inbox=tilde(path)))
    else:
        raise PeerError(f"unknown setting {key!r} (peers.py --help)")


# -- CLI ------------------------------------------------------------------------------------------
def take(args, flag, has_value=True):
    """Pop --flag [VALUE] from args."""
    if flag not in args:
        return None
    i = args.index(flag)
    if not has_value:
        args.pop(i)
        return True
    if i + 1 >= len(args):
        raise PeerError(f"{flag} needs a value")
    value = args[i + 1]
    del args[i:i + 2]
    return value


def main(argv):
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd, args = argv[0], list(argv[1:])
    as_json = bool(take(args, "--json", False))
    to = take(args, "--to")
    if cmd == "status":
        data = status()
        print(json.dumps(data, ensure_ascii=False) if as_json else human_status(data))
    elif cmd == "pair":
        port = take(args, "--port")
        return 0 if pair_host(UI(as_json), int(port) if port and port.isdigit() else 0) == "paired" else 1
    elif cmd == "join":
        return 0 if pair_join(UI(as_json), args[0] if args else None) == "paired" else 1
    elif cmd == "discover":
        found = mdns_browse(PAIR_SERVICE if "--pairing" in args else SERVICE)
        _, fp = identity(create=False) if x509 is not None else (None, None)
        found = [dict(f, me=bool(fp) and f["id"] == fp[:16]) for f in found]
        print(json.dumps(found) if as_json else "\n".join(f"{f['name']}  {f['address']}:{f['port']}  {f['id']}"
                                                            for f in found) or "nothing found")
    elif cmd == "unpair" and len(args) == 1:
        print(unpair(args[0]))
    elif cmd == "name" and len(args) == 1:
        if not valid_name(args[0]):
            raise PeerError("a name is 1-32 letters, digits, spaces and . ' ( ) -")
        update(lambda c: c.update(name=args[0]))
    elif cmd == "set" and len(args) == 2:
        set_option(*args)
    elif cmd in ("clipboard", "memory") and args in (["on"], ["off"]):
        set_privacy(f"machines_{cmd}", args[0] == "on")
    elif cmd == "ping":
        conf = load()
        peers = [choose(conf, args[0] if args else to)] if args or to else conf["peers"]
        out = []
        for peer in peers:
            t0 = time.monotonic()
            try:
                answer = request(peer, {"op": "hello"}, conf)
                out.append({"name": peer["name"], "ok": True, "ms": round((time.monotonic() - t0) * 1000),
                            "accepts": answer.get("accepts")})
            except PeerError as exc:
                out.append({"name": peer["name"], "ok": False, "why": str(exc)})
        print(json.dumps(out) if as_json else "\n".join(
            f"{o['name']}: {o['ms']} ms, accepts {o['accepts']}" if o["ok"] else f"{o['name']}: {o['why']}"
            for o in out) or "no machine is paired")
        return 0 if out and all(o["ok"] for o in out) else 1
    elif cmd == "send" and args:
        peer = choose(load(), to)
        return say_sent(peer, send_targets(peer, args))
    elif cmd == "send-window":
        target, why = window_target(active_window())
        if not target:
            notify("Nothing to send from this window", why, "normal")
            return 1
        peer = choose(load(), to)
        return say_sent(peer, send_targets(peer, [target]))
    elif cmd == "send-clipboard":
        return send_clipboard(choose(load(), to))
    elif cmd == "context":
        conf = load()
        peers = [choose(conf, to)] if to else conf["peers"]
        print("\n".join(context_cmd(peers, args[0] if args else None)))
    elif cmd == "session" and args in (["send"], ["get"]):
        return session_cmd(args[0], choose(load(), to))
    elif cmd == "recall" and args:
        notify_mode = bool(take(args, "--notify", False))
        question = " ".join(a for a in args if a != "--").strip()
        peer = choose(load(), to, ask=not as_json)
        if notify_mode:
            return notify_recall(peer, question)
        answer = recall(peer, question)
        print(json.dumps(answer, ensure_ascii=False) if as_json else answer.get("answer", ""))
    elif cmd == "kvm" and args:
        sub = args[0]
        if sub == "status":
            data = kvm_status()
            print(json.dumps(data) if as_json else "\n".join(f"{k}: {v}" for k, v in data.items()))
        elif sub == "install":
            print(kvm_install())
        elif sub in ("on", "off", "toggle"):
            msg = kvm_set(not load()["kvm"] if sub == "toggle" else sub == "on")
            print(msg) if sys.stdin.isatty() else notify(msg)
        elif sub == "side" and len(args) == 3:
            print(kvm_side(args[1], args[2]))
        elif sub == "config":
            write_kvm_config()
            print(LANMOUSE_CONF)
        else:
            raise PeerError("kvm status|install|on|off|toggle|side NAME SIDE")
    elif cmd == "serve":
        return Daemon().serve()
    elif cmd == "clip-hook":
        clip_hook()
    else:
        raise PeerError(f"unknown command {cmd!r} (peers.py --help)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except (PeerError, OSError, ssl.SSLError) as exc:
        why = str(exc) if isinstance(exc, PeerError) else f"{getattr(exc, 'reason', None) or exc}"
        if "--json" in sys.argv:
            print(json.dumps({"event": "error", "why": why}, ensure_ascii=False), flush=True)
            sys.exit(1)
        if sys.stdin.isatty() or not os.environ.get("WAYLAND_DISPLAY"):
            sys.exit(f"peers: {why}")
        notify("Machines", why, "normal")
        sys.exit(1)
