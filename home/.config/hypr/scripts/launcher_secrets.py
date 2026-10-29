#!/usr/bin/env python3
"""Passwords in the launcher (launcher.py, "pw <words>"): the entries of
your password manager whose name or fields have the words; Enter copies the
password to the clipboard and clears it again 30 seconds later -- only if
the clipboard still holds it then (something copied since is left alone).

Any Secret Service provider works (org.freedesktop.secrets on the session
bus, the freedesktop standard): KeePassXC with Settings > Secret Service
Integration on (and the groups to share picked in the database's settings),
GNOME Keyring, KWallet's compatibility service. The rows say which one
answered (provider_label). Nothing here starts one: with no provider running
the launcher shows a single row saying how to get one; with the collections
locked, a single row that asks the provider to unlock them (its own dialog,
Service.Unlock + Prompt) on Enter.

What stays out of sight:
  * the secret is fetched from the provider only on Enter, and not by the
    launcher: it starts `launcher_secrets.py copy <item path> 30` (copy_argv;
    the path is all its argv holds) in a session of its own, which asks the
    provider over a "plain" Secret Service session on the session bus (the
    bus is your own user's) and hands the secret to `wl-copy --sensitive` on
    its stdin -- never in an argv, an environment variable, a log line or
    stdout;
  * --sensitive marks the copy as a password (x-kde-passwordManagerHint), so
    the clipboard history (cliphist) does not keep it and the launcher's own
    "just copied" suggestions skip it;
  * the same process then waits the 30 s (it outlives the launcher's card)
    and compares what the clipboard holds with the secret -- in memory,
    never written anywhere -- clearing it only when they are the same;
  * the search index holds names and attributes only (Secret Service keeps
    those unencrypted by design), minus any attribute that looks like a
    secret itself (SECRET_ATTRS: notes, passwords, one-time codes).

    launcher_secrets.py status                what the launcher would find
                                              (provider, counts; no names)
    launcher_secrets.py copy ITEM [SECONDS]   Enter on a row (above)
    launcher_secrets.py unlock COLLECTION...  ask the provider to unlock

Pure parts (tests/test_launcher_secrets.py): provider_label(), safe_attrs(),
searchable(), search(), subtitle(), same_secret(), hold() (with fakes). The D-Bus side goes through one call()
the tests replace with a fake service.
"""
import os
import subprocess
import sys
import threading
import time

BUS = "org.freedesktop.secrets"
ROOT = "/org/freedesktop/secrets"
SERVICE = "org.freedesktop.Secret.Service"
COLLECTION = "org.freedesktop.Secret.Collection"
ITEM = "org.freedesktop.Secret.Item"
PROMPT = "org.freedesktop.Secret.Prompt"
PROPS = "org.freedesktop.DBus.Properties"
CLEAR_AFTER = 30                # seconds the password stays on the clipboard
FRESH = 60                      # seconds an index is used before it is read again
LIMIT = 12                      # rows shown
TIMEOUT_MS = 2000               # per D-Bus call: a provider that hangs must not hang the launcher
UNLOCK_TIMEOUT_MS = 120000      # a call that may wait for you (an access prompt); never in the GTK thread
# Well-known names a provider also owns: which one answers for
# org.freedesktop.secrets is the one whose owner is the same connection.
PROVIDERS = (("org.keepassxc.KeePassXC.MainWindow", "KeePassXC"),
             ("org.gnome.keyring", "GNOME Keyring"),
             ("org.kde.kwalletd6", "KWallet"), ("org.kde.kwalletd5", "KWallet"),
             ("org.kde.secretservicecompat", "KWallet"))
SECRET_ATTRS = ("note", "password", "passwd", "secret", "otp", "totp", "pin", "token", "key")
SHOWN_ATTRS = ("UserName", "username", "user", "account", "URL", "url", "server", "service", "Path")


# -- pure ---------------------------------------------------------------------------------
def provider_label(secrets_owner, owners):
    """Who answers for org.freedesktop.secrets: owners maps the well-known
    names of PROVIDERS to their unique connection (":1.42"); the one shared
    with the secrets name wins. "Secret Service" when none is known."""
    if secrets_owner:
        for name, label in PROVIDERS:
            if owners.get(name) == secrets_owner:
                return label
    return "Secret Service"


def safe_attrs(attrs):
    """The attributes worth searching and showing: not ones that look like a
    secret themselves, nor KeePassXC's internal ids."""
    out = {}
    for k, v in (attrs or {}).items():
        low = str(k).lower()
        if any(s in low for s in SECRET_ATTRS) or low in ("uuid", "xdg:schema"):
            continue
        out[str(k)] = str(v)
    return out


def searchable(label, attrs):
    """One lower-case string a query's words are looked for in."""
    return " ".join([label or ""] + list(safe_attrs(attrs).values())).lower()


def search(index, words, limit=LIMIT):
    """The index rows ({path, label, attrs, text}) with every word, those
    whose LABEL starts with the first word first, then by label."""
    words = (words or "").lower().split()
    found = [r for r in index if all(w in r["text"] for w in words)]
    first = words[0] if words else ""
    found.sort(key=lambda r: (not (r["label"] or "").lower().startswith(first), (r["label"] or "").lower()))
    return found[:limit]


def subtitle(row, provider):
    """"user · example.com · Group/Sub  ·  KeePassXC: Enter copies, cleared in 30 s"."""
    attrs = safe_attrs(row.get("attrs"))
    seen, parts = set(), []
    for k in SHOWN_ATTRS:
        v = attrs.get(k)
        if v and v not in seen and v != row.get("label"):
            seen.add(v)
            parts.append(v)
    where = " · ".join(parts[:3])
    tail = f"{provider}: Enter copies the password, cleared in {CLEAR_AFTER} s"
    return f"{where}  ·  {tail}" if where else tail


def same_secret(secret, pasted):
    """Is what the clipboard holds now (wl-paste) still the secret?
    wl-paste -n drops one trailing newline, so that is forgiven."""
    if pasted is None:
        return False
    return pasted == secret or pasted == secret.rstrip(b"\n") or pasted.rstrip(b"\n") == secret.rstrip(b"\n")


# -- D-Bus --------------------------------------------------------------------------------
_CONN = []      # the session bus, kept: GIO holds its shared connection only weakly, and a
                # connection that closes takes its Secret Service sessions with it


def _bus():
    from gi.repository import Gio
    if not _CONN:
        _CONN.append(Gio.bus_get_sync(Gio.BusType.SESSION, None))
    return _CONN[0]


def _gio_call(bus_name, path, iface, method, params=None, reply=None, timeout=TIMEOUT_MS):
    """One synchronous call on the session bus; the reply unpacked to
    Python. Raises on any error (the callers turn that into a state)."""
    from gi.repository import Gio, GLib
    out = _bus().call_sync(bus_name, path, iface, method, params,
                         GLib.VariantType.new(reply) if reply else None,
                         Gio.DBusCallFlags.NO_AUTO_START, timeout, None)
    return out.unpack() if out is not None else ()


def _v(fmt, *values):
    from gi.repository import GLib
    return GLib.Variant(fmt, values)


class SecretService:
    """The provider, asked through `call` (_gio_call; a fake in the tests).
    Never raises: everything comes back as a state."""

    def __init__(self, call=None, variant=None):
        self.call = call or _gio_call
        self.v = variant or _v

    def _dbus(self, method, *args, fmt="(s)", reply=None):
        return self.call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                         method, self.v(fmt, *args) if args else None, reply)

    def owner(self, name):
        try:
            return self._dbus("GetNameOwner", name, reply="(s)")[0]
        except Exception:  # noqa: BLE001 -- no owner is an answer
            return None

    def provider(self):
        """(running, label)."""
        me = self.owner(BUS)
        if not me:
            return False, "Secret Service"
        return True, provider_label(me, {n: self.owner(n) for n, _ in PROVIDERS})

    def prop(self, path, iface, name):
        return self.call(BUS, path, PROPS, "Get", self.v("(ss)", iface, name), "(v)")[0]

    def scan(self):
        """{"state": "none" | "empty" | "locked" | "ok" | "error", "provider",
        "items": [{path, label, attrs, text}], "locked": [collection paths]}.
        "ok" when at least one collection is open (locked ones are listed
        too, for an Unlock row)."""
        running, label = self.provider()
        out = {"state": "none", "provider": label, "items": [], "locked": []}
        if not running:
            return out
        try:
            collections = list(self.prop(ROOT, SERVICE, "Collections") or ())
        except Exception as exc:  # noqa: BLE001
            return dict(out, state="error", error=type(exc).__name__)
        if not collections:
            return dict(out, state="empty")
        opened = 0
        for c in collections:
            try:
                if self.prop(c, COLLECTION, "Locked"):
                    out["locked"].append(c)
                    continue
                items = self.prop(c, COLLECTION, "Items") or ()
            except Exception:  # noqa: BLE001 -- one bad collection is not all of them
                continue
            opened += 1
            for path in items:
                try:
                    props = self.call(BUS, path, PROPS, "GetAll", self.v("(s)", ITEM), "(a{sv})")[0]
                except Exception:  # noqa: BLE001
                    continue
                if props.get("Locked"):
                    continue
                lab, attrs = props.get("Label") or "", dict(props.get("Attributes") or {})
                out["items"].append({"path": path, "label": lab, "attrs": safe_attrs(attrs),
                                     "text": searchable(lab, attrs)})
        out["state"] = "ok" if opened else "locked"
        return out

    def unlock(self, paths):
        """Ask the provider to unlock these collections: its own dialog comes
        up (the Prompt). True when they are unlocked (at once, or by you in
        that dialog)."""
        try:
            _done, prompt = self.call(BUS, ROOT, SERVICE, "Unlock", self.v("(ao)", list(paths)), "(aoo)")
            if prompt and prompt != "/":
                return self.prompt(prompt)
            return True
        except Exception:  # noqa: BLE001
            return False

    def prompt(self, path, seconds=UNLOCK_TIMEOUT_MS // 1000):
        """Show a provider's prompt and wait for its Completed signal (a
        provider may drop the prompt of a caller that has gone). True unless
        it was dismissed or never answered."""
        from gi.repository import Gio, GLib
        conn, loop, ok = _bus(), GLib.MainLoop(), [False]

        def completed(_conn, _sender, _path, _iface, _signal, params):
            ok[0] = not params.unpack()[0]      # (dismissed, result)
            loop.quit()
        sub = conn.signal_subscribe(None, PROMPT, "Completed", path, None, Gio.DBusSignalFlags.NONE, completed)
        try:
            self.call(BUS, path, PROMPT, "Prompt", self.v("(s)", ""), None)
            GLib.timeout_add_seconds(seconds, lambda: loop.quit() or False)
            loop.run()
        finally:
            conn.signal_unsubscribe(sub)
        return ok[0]

    def secret(self, item):
        """The item's secret as bytes, or None. A plain session, closed
        right after."""
        session = None
        try:
            from gi.repository import GLib
            _out, session = self.call(BUS, ROOT, SERVICE, "OpenSession",
                                      self.v("(sv)", "plain", GLib.Variant("s", "")), "(vo)")
            # Long timeout: KeePassXC may first ask you to allow the access.
            got = self.call(BUS, item, ITEM, "GetSecret", self.v("(o)", session), "((oayays))",
                            UNLOCK_TIMEOUT_MS)[0]
            return bytes(got[2])
        except Exception:  # noqa: BLE001 -- locked, gone, refused: no secret
            return None
        finally:
            if session:
                try:
                    self.call(BUS, session, "org.freedesktop.Secret.Session", "Close", None, None)
                except Exception:  # noqa: BLE001
                    pass


class Index:
    """The launcher's view: scanned in a thread when "pw" is first typed and
    again after FRESH seconds; on_ready (called from that thread: the
    launcher hops to GTK with GLib.idle_add) when a scan lands."""

    def __init__(self, service=None, on_ready=None):
        self.service = service or SecretService()
        self.on_ready = on_ready
        self.result = None
        self.when = 0.0
        self.busy = False
        self.lock = threading.Lock()

    def get(self, now=None):
        """The last scan (None before the first), starting a new one when stale."""
        now = time.time() if now is None else now
        with self.lock:
            stale = self.result is None or now - self.when > FRESH
            if stale and not self.busy:
                self.busy = True
                threading.Thread(target=self._scan, daemon=True).start()
            return self.result

    def _scan(self):
        try:
            got = self.service.scan()
        except Exception as exc:  # noqa: BLE001
            got = {"state": "error", "provider": "Secret Service", "items": [], "locked": [],
                   "error": type(exc).__name__}
        with self.lock:
            self.result, self.when, self.busy = got, time.time(), False
        if self.on_ready:
            self.on_ready()

    def forget(self):
        with self.lock:
            self.result, self.when = None, 0.0


# -- the clipboard --------------------------------------------------------------------------
if os.path.dirname(os.path.abspath(__file__)) not in sys.path:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import desk_common  # noqa: E402  (notify: the notification, through scripts/notify)


def copy_argv(item, seconds=CLEAR_AFTER):
    """What the launcher starts on Enter: this file, which fetches the
    secret itself -- so it never passes through the launcher -- copies it
    and clears it. Only the item's D-Bus path is in the argv."""
    return [sys.executable, os.path.abspath(__file__), "copy", item, str(int(seconds))]


def unlock_argv(paths):
    return [sys.executable, os.path.abspath(__file__), "unlock", *paths]


def _paste():
    try:
        r = subprocess.run(["wl-paste", "-n"], capture_output=True, timeout=3)
        return r.stdout if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def hold(secret, seconds, run=subprocess.run, sleep=time.sleep, paste=_paste, copied=lambda: None):
    """Copy, (say so: copied()), wait, clear if unchanged. Returns "cleared",
    "kept" (something else was copied since) or "failed" (wl-copy would not
    take it). The secret goes to wl-copy on its stdin."""
    ok = False
    for argv in (["wl-copy", "--sensitive"], ["wl-copy"]):     # --sensitive: wl-clipboard 2.2+
        try:
            ok = run(argv, input=secret, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     timeout=5).returncode == 0
        except (OSError, subprocess.SubprocessError):
            ok = False
        if ok:
            break
    if not ok:
        return "failed"
    copied()
    sleep(seconds)
    if not same_secret(secret, paste()):
        return "kept"
    try:
        run(["wl-copy", "--clear"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
    except (OSError, subprocess.SubprocessError):
        pass
    return "cleared"


def notify(title, body, icon="dialog-password"):
    desk_common.notify(title, body, app="Launcher", icon=icon, timeout=5)


def copy(item, seconds, service=None, say=notify):
    """`launcher_secrets.py copy ITEM SECONDS`: the whole Enter of a password
    row, in its own process. Returns hold()'s answer, or "unread"."""
    service = service or SecretService()
    _running, provider = service.provider()
    try:
        label = service.prop(item, ITEM, "Label") or "(no name)"
    except Exception:  # noqa: BLE001
        label = "(no name)"
    secret = service.secret(item)
    if not secret:
        say(f"{provider}: no password copied",
            f"\"{label}\" could not be read -- locked, refused, or it has no password")
        return "unread"
    got = hold(secret, seconds, copied=lambda: say(
        "Password copied", f"\"{label}\" from {provider}  ·  cleared from the clipboard in {seconds} s"))
    if got == "failed":
        say(f"{provider}: no password copied", "wl-copy would not take it (no Wayland clipboard?)",
            "dialog-warning")
    return got


def main(argv):
    if argv[:1] == ["copy"] and len(argv) >= 2:
        seconds = int(argv[2]) if len(argv) > 2 and argv[2].isdigit() else CLEAR_AFTER
        copy(argv[1], seconds)
        return 0
    if argv[:1] == ["unlock"]:
        return 0 if SecretService().unlock(argv[1:]) else 1
    if argv[:1] == ["status"]:
        # Names only, never a secret: how many entries, which provider, locked or not.
        s = SecretService().scan()
        print(f"{s['provider']}: {s['state']}, {len(s['items'])} entries open, "
              f"{len(s['locked'])} collection(s) locked")
        return 0
    sys.stderr.write(__doc__.split("Pure parts")[0].strip().splitlines()[0] + "\n"
                     "usage: launcher_secrets.py status | copy ITEM [SECONDS] | unlock COLLECTION...\n")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
