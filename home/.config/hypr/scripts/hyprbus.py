#!/usr/bin/env python3
"""One reader of Hyprland's event socket (socket2), shared (hyprbus.service).

Every daemon that follows Hyprland's events used to open its own connection
to .socket2.sock, and Hyprland writes every event to every one of them, from
its own main loop: a title change in a terminal woke a dozen processes, most
of which only care about a reload or a new window. hyprbus holds the one
connection and passes each line on only to the subscribers that asked for
that event's name.

    hyprbus.py serve              the relay (hyprbus.service)
    hyprbus.py status             is it running, who listens to what, and the counts
    hyprbus.py tail [NAME ...]    print the events (all, or just these names)

For the scripts:

    import hyprbus
    sock = hyprbus.connect({"openwindow", "closewindow"})   # a socket, read like socket2
    for name, data in hyprbus.subscribe({"configreloaded"}):
        ...                                                   # or an endless iterator

The relay's lines are socket2's lines, byte for byte, so a reader's parsing
does not change. Nothing depends on the relay: when it is not running,
connect() opens Hyprland's own socket instead (the reader then gets every
event, as before, and filters them itself as it always has).
HYPRBUS_OFF=1 always goes direct.

The protocol: a subscriber connects to $XDG_RUNTIME_DIR/hyprbus.sock and
sends one line, the event names separated by spaces ("*" for every event,
"?" for the status as JSON). From then on it only reads.

  * A slow subscriber is never waited on: what it has not read yet is kept
    up to MAX_BACKLOG bytes, past that it is dropped. It sees the end of the
    stream and reconnects, as after a Hyprland restart.
  * When Hyprland goes away the relay ends every subscriber's stream too --
    the end a direct reader sees -- and stops listening until the next
    Hyprland (a new instance signature) is up, so a reader that reconnects
    and re-reads its state reads the new one.
"""
import json
import os
import selectors
import socket
import struct
import sys
import time

RUNTIME = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
RELAY = os.path.join(RUNTIME, "hyprbus.sock")
MAX_BACKLOG = 1 << 20       # bytes a subscriber may leave unread before it is dropped
HELLO_S = 5.0               # a subscriber has this long to say what it wants
RETRY_S = 0.5               # the relay looks for Hyprland again this often
CLIENT_RETRY_S = 2.0        # subscribe(): between two failed connects
ALL = None                  # a subscription to every event


# -- pure ------------------------------------------------------------------------------
def event_name(line):
    """b"openwindow>>..." -> b"openwindow"."""
    return line.split(b">>", 1)[0]


def hello(names):
    """The first line a subscriber sends: the names, or "*" for all."""
    if names is ALL:
        return b"*\n"
    names = sorted({n.decode() if isinstance(n, bytes) else str(n) for n in names})
    if not names or any(not n or not n.replace("_", "").isalnum() for n in names):
        raise ValueError(f"hyprbus: not event names: {names!r}")
    return (" ".join(names) + "\n").encode()


def parse_hello(line):
    """A subscriber's first line -> frozenset of names (bytes), ALL for "*",
    "status" for "?", or "" when it is not a subscription."""
    words = line.strip().split()
    if words == [b"*"]:
        return ALL
    if words == [b"?"]:
        return "status"
    if not words or any(not w.replace(b"_", b"").isalnum() for w in words):
        return ""
    return frozenset(words)


def wants(names, name):
    return names is ALL or name in names


def split_lines(buf, chunk):
    """(complete lines, the unfinished rest) after `chunk` arrives on `buf`."""
    *lines, rest = (buf + chunk).split(b"\n")
    return [l for l in lines if l], rest


def route(lines, subscriptions):
    """{key: bytes to send} for socket2 `lines`, given {key: names}: each
    subscriber gets its lines in one write, nobody gets an empty one."""
    named = [(event_name(l), l) for l in lines]
    out = {}
    for key, names in subscriptions.items():
        mine = [l for n, l in named if wants(names, n)]
        if mine:
            out[key] = b"\n".join(mine) + b"\n"
    return out


def instance_dir(base=None, env=None):
    """$XDG_RUNTIME_DIR/hypr/<instance> with a live socket2: the one named by
    HYPRLAND_INSTANCE_SIGNATURE when its socket is there, else the newest
    (a service whose environment still names a Hyprland that has gone)."""
    base = base or os.path.join(RUNTIME, "hypr")
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE") if env is None else env
    if sig and os.path.exists(os.path.join(base, sig, ".socket2.sock")):
        return os.path.join(base, sig)
    try:
        dirs = [os.path.join(base, d) for d in os.listdir(base)]
        dirs = [d for d in dirs if os.path.exists(os.path.join(d, ".socket2.sock"))]
        return max(dirs, key=os.path.getmtime) if dirs else None
    except OSError:
        return None


def socket2_path():
    folder = instance_dir()
    return os.path.join(folder, ".socket2.sock") if folder else None


# -- the client side -------------------------------------------------------------------
def _via_relay(names, path):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.settimeout(1.0)
        s.connect(path)
        s.sendall(hello(names))
        s.settimeout(None)
        return s
    except OSError:
        s.close()
        return None


def connect(names=ALL, direct=None, relay=None):
    """A connected socket that reads like socket2: through the relay, with
    only `names` (an iterable of event names, or ALL), or -- the relay not
    running -- Hyprland's own socket2 at `direct` (a path, or a function
    returning one; default: the current instance's), every event. Raises
    OSError when neither can be reached."""
    if names is not ALL:
        hello(names)                    # a bad name fails here, not in the relay
    if not os.environ.get("HYPRBUS_OFF"):
        s = _via_relay(names, relay or RELAY)
        if s is not None:
            return s
    path = (direct() if callable(direct) else direct) if direct is not None else socket2_path()
    if not path:
        raise OSError("hyprbus: no Hyprland instance")
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.connect(path)
    except OSError:
        s.close()
        raise
    return s


def subscribe(names=ALL, direct=None, relay=None, sleep=time.sleep):
    """Endless (name, data) strings for the events in `names`, reconnecting
    (relay or direct) after Hyprland restarts or the relay drops us."""
    keep = ALL if names is ALL else {n.encode() if isinstance(n, str) else n for n in names}
    while True:
        try:
            sock = connect(names, direct=direct, relay=relay)
        except OSError:
            sleep(CLIENT_RETRY_S)
            continue
        buf = b""
        with sock:
            while True:
                try:
                    chunk = sock.recv(65536)
                except OSError:
                    chunk = b""
                if not chunk:
                    break
                lines, buf = split_lines(buf, chunk)
                for line in lines:
                    name, _, data = line.partition(b">>")
                    if wants(keep, name):       # direct: every event comes, keep ours
                        yield name.decode(errors="replace"), data.decode(errors="replace")
        sleep(0.2)


def status(relay=None):
    """The running relay's status dict, or None."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(2)
            s.connect(relay or RELAY)
            s.sendall(b"?\n")
            data = b""
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    break
                data += chunk
        return json.loads(data)
    except (OSError, ValueError):
        return None


# -- the relay -------------------------------------------------------------------------
def peer_name(sock):
    """'<pid> <script>' of the process on the other end, for the status."""
    try:
        pid = struct.unpack("3i", sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED,
                                                  struct.calcsize("3i")))[0]
        with open(f"/proc/{pid}/cmdline", "rb") as handle:
            argv = [a.decode(errors="replace") for a in handle.read().split(b"\0") if a]
        script = next((os.path.basename(a) for a in argv[1:] if a.endswith(".py")), None)
        return f"{pid} {script or os.path.basename(argv[0]) if argv else '?'}"
    except (OSError, struct.error, IndexError):
        return "?"


class Subscriber:
    """One subscriber's socket, its names and what it has not read yet."""

    def __init__(self, sock, names, limit=MAX_BACKLOG):
        self.sock, self.names, self.limit = sock, names, limit
        self.out = bytearray()
        self.who = peer_name(sock)

    def offer(self, data):
        """Queue `data` and send what the socket takes now. False: the
        backlog is past the limit (drop this subscriber)."""
        self.out += data
        return self.flush()

    def flush(self):
        while self.out:
            try:
                sent = self.sock.send(self.out)
            except (BlockingIOError, InterruptedError):
                break
            except OSError:
                return False
            del self.out[:sent]
        return len(self.out) <= self.limit


class Relay:
    """The one socket2 connection and the subscribers' sockets, in a
    selector loop that never blocks on any one of them."""

    def __init__(self, path=RELAY, find=socket2_path, log=print, clock=time.monotonic, limit=MAX_BACKLOG):
        self.path, self.find, self.log, self.clock, self.limit = path, find, log, clock, limit
        self.sel = selectors.DefaultSelector()
        self.hypr = self.listener = None
        self.hypr_path, self.buf = None, b""
        self.subs = {}          # fd -> Subscriber
        self.waiting = {}       # fd -> (sock, buf, deadline): connected, not said hello yet
        self.counts = {"lines": 0, "writes": 0, "fanout_saved": 0, "dropped": 0}
        self.since = time.time()

    # Hyprland
    def attach(self):
        path = self.find()
        if not path:
            return False
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            s.connect(path)
        except OSError:
            s.close()
            return False
        s.setblocking(False)
        self.hypr, self.hypr_path, self.buf = s, path, b""
        self.sel.register(s, selectors.EVENT_READ, "hypr")
        self.listen()
        self.log(f"hyprbus: following {os.path.basename(os.path.dirname(path))[:12]}…")
        return True

    def detach(self, why):
        """Hyprland went away: end every stream, stop listening."""
        self.log(f"hyprbus: {why}; ending {len(self.subs)} subscriber stream(s)")
        if self.hypr is not None:
            self.sel.unregister(self.hypr)
            self.hypr.close()
        self.hypr = None
        for fd in list(self.subs):
            self.drop(fd, None)
        for fd in list(self.waiting):
            self.drop(fd, None)
        self.unlisten()

    def listen(self):
        if self.listener is not None:
            return
        try:
            os.unlink(self.path)
        except OSError:
            pass
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        old = os.umask(0o177)
        try:
            s.bind(self.path)
        finally:
            os.umask(old)
        s.listen(32)
        s.setblocking(False)
        self.listener = s
        self.sel.register(s, selectors.EVENT_READ, "listen")

    def unlisten(self):
        if self.listener is None:
            return
        self.sel.unregister(self.listener)
        self.listener.close()
        self.listener = None
        try:
            os.unlink(self.path)
        except OSError:
            pass

    # subscribers
    def accept(self):
        try:
            sock, _ = self.listener.accept()
        except (BlockingIOError, InterruptedError):
            return
        sock.setblocking(False)
        self.waiting[sock.fileno()] = (sock, b"", self.clock() + HELLO_S)
        self.sel.register(sock, selectors.EVENT_READ, "hello")

    def read_hello(self, fd):
        sock, buf, deadline = self.waiting[fd]
        try:
            chunk = sock.recv(4096)
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            chunk = b""
        if not chunk:
            self.drop(fd, None)
            return
        buf += chunk
        if b"\n" not in buf:
            if len(buf) > 4096:
                self.drop(fd, "a hello too long")
            else:
                self.waiting[fd] = (sock, buf, deadline)
            return
        names = parse_hello(buf.split(b"\n", 1)[0])
        if names == "status":
            del self.waiting[fd]
            self.sel.unregister(sock)
            try:
                sock.setblocking(True)
                sock.settimeout(1)
                sock.sendall(json.dumps(self.status()).encode())
            except OSError:
                pass
            sock.close()
            return
        if names == "":
            self.drop(fd, "not a subscription")
            return
        del self.waiting[fd]
        self.subs[fd] = Subscriber(sock, names, self.limit)
        self.sel.modify(sock, selectors.EVENT_READ, "sub")

    def drop(self, fd, why):
        entry = self.subs.pop(fd, None)
        sock = entry.sock if entry else (self.waiting.pop(fd, (None,))[0])
        if sock is None:
            return
        if why:
            self.counts["dropped"] += 1
            self.log(f"hyprbus: dropped {entry.who if entry else 'a subscriber'}: {why}")
        try:
            self.sel.unregister(sock)
        except (KeyError, ValueError):
            pass
        sock.close()

    def sub_readable(self, fd):
        """A subscriber only reads; anything readable is its end (or noise)."""
        sub = self.subs[fd]
        try:
            chunk = sub.sock.recv(4096)
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            chunk = b""
        if not chunk:
            self.drop(fd, None)

    def sub_writable(self, fd):
        sub = self.subs[fd]
        if not sub.flush():
            self.drop(fd, "gone")
        elif not sub.out:
            self.sel.modify(sub.sock, selectors.EVENT_READ, "sub")

    # the events
    def read_hypr(self):
        try:
            chunk = self.hypr.recv(65536)
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            chunk = b""
        if not chunk:
            self.detach("Hyprland closed its event socket")
            return
        lines, self.buf = split_lines(self.buf, chunk)
        if not lines:
            return
        self.counts["lines"] += len(lines)
        out = route(lines, {fd: s.names for fd, s in self.subs.items()})
        self.counts["writes"] += len(out)
        self.counts["fanout_saved"] += len(self.subs) - len(out)
        for fd, data in out.items():
            sub = self.subs[fd]
            if not sub.offer(data):
                self.drop(fd, f"more than {self.limit // 1024} KiB unread")
            elif sub.out:
                self.sel.modify(sub.sock, selectors.EVENT_READ | selectors.EVENT_WRITE, "sub")

    def expire(self):
        now = self.clock()
        for fd, (_s, _b, deadline) in list(self.waiting.items()):
            if now >= deadline:
                self.drop(fd, "no hello")

    def status(self):
        return {"pid": os.getpid(), "since": round(self.since),
                "hyprland": os.path.basename(os.path.dirname(self.hypr_path or "")) if self.hypr else None,
                "subscribers": [{"who": s.who, "events": "*" if s.names is ALL else sorted(n.decode() for n in s.names),
                                 "backlog": len(s.out)} for s in self.subs.values()],
                **self.counts}

    def step(self, timeout):
        for key, mask in self.sel.select(timeout):
            fd, what = key.fd, key.data
            # A batch can hold Hyprland's end and a new connection both:
            # once detach() has run, neither socket is ours any more.
            if what == "hypr" and self.hypr is not None:
                self.read_hypr()
            elif what == "listen" and self.listener is not None:
                self.accept()
            elif what == "hello" and fd in self.waiting:
                self.read_hello(fd)
            elif what == "sub" and fd in self.subs:
                if mask & selectors.EVENT_WRITE:
                    self.sub_writable(fd)
                if mask & selectors.EVENT_READ and fd in self.subs:
                    self.sub_readable(fd)
        self.expire()

    def run(self, stop=lambda: False, idle=1.0):
        """Until stop() (checked at least every `idle` s) or an exception
        (serve's SIGTERM): the subscribers' streams end and the socket goes."""
        try:
            while not stop():
                if self.hypr is None and not self.attach():
                    time.sleep(RETRY_S)
                    continue
                self.step(idle)
        finally:
            self.detach("stopping")


def _stop(*_):
    raise SystemExit(0)                 # out of select() now, through run()'s finally


def serve():
    import signal
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    if status() is not None:
        sys.exit("hyprbus: already running")
    Relay(log=lambda m: print(m, flush=True)).run(idle=60)


def main(argv):
    cmd = argv[0] if argv else "status"
    if cmd == "serve":
        serve()
    elif cmd == "status":
        st = status()
        if st is None:
            print("hyprbus: not running (readers go to Hyprland directly)")
            sys.exit(1)
        if "--json" in argv:
            print(json.dumps(st))
            return
        up = max(1, time.time() - st["since"])
        print(f"hyprbus {st['pid']}: Hyprland {(st['hyprland'] or 'none')[:12]}, "
              f"{st['lines']} events in {up / 3600:.1f} h, {st['writes']} deliveries, "
              f"{st['fanout_saved']} wake-ups saved, {st['dropped']} dropped")
        for s in st["subscribers"]:
            print(f"  {s['who']:<28} {' '.join(s['events']) if isinstance(s['events'], list) else s['events']}")
    elif cmd == "tail":
        try:
            for name, data in subscribe(argv[1:] or ALL):
                print(f"{name}>>{data}", flush=True)
        except KeyboardInterrupt:
            pass
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
