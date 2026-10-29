#!/usr/bin/env python3
"""Your phone over KDE Connect (kdeconnectd; installed and its firewall ports
opened by setup-root.sh, then paired once from the phone's KDE Connect app).

    phone.py bar               waybar JSON for custom/phone: a phone glyph and
                               the battery while a paired phone is reachable,
                               nothing otherwise (on the pill: click opens
                               Settings > Devices, middle-click rings it,
                               right-click sends the clipboard)
    phone.py ring              make the phone ring (find it)
    phone.py share <file>...   send files to it
    phone.py clip              send the clipboard's text to it
    phone.py ping              a test notification on it
    phone.py list [--json]     paired devices, reachable or not

Phone notifications arrive on the desktop by themselves (kdeconnectd posts
them like any app), and the clipboard is shared both ways when the phone
app allows it. Actions go through kdeconnect-cli; which phones are paired
and reachable, and the battery, are asked of kdeconnectd over D-Bus
(busctl, one call each): `kdeconnect-cli -l` waits on a network discovery
and took 2 s, the daemon's devices list answers in a few ms. With more than
one phone, the first reachable one is used.

The pill (custom/phone) is pushed, not polled: the watcher below also
follows kdeconnectd's device signals (reachable / gone / paired / battery)
and redraws it (bar_signals.poke("phone")); the module's long interval is
only a safety net. The bar never starts kdeconnectd (--auto-start=no): no
daemon, no pill.

Handoff, desktop -> phone:

    phone.py open [URL]        open a link on the phone (its browser): URL, else
                               the page in the browser you used last (tab_url),
                               else the clipboard when it holds a link
    phone.py tab [--print]     the same, only ever the browser's page
                               (--print: say the address, send nothing)
    phone.py file [PATH...]    send files; none given: a file picker (zenity),
                               opened in the folder of the file manager you
                               used last
    phone.py file --copied     send the files copied in Files (Ctrl+C there:
                               text/uri-list on the clipboard) -- the cheap
                               way to "the selection": Nautilus has no API
                               that tells another program what is selected

Handoff, phone -> desktop (phone.py watch, phone-handoff.service):

    phone.py watch             follow kdeconnectd's D-Bus signals
    phone.py codes on|off      offer 2FA codes from the phone's notifications
                               (privacy.conf phone_codes; off as shipped)
    phone.py status [--json]   what the handoff can do now, for Settings > Devices

What each direction rests on, and what KDE Connect does by itself:

  text      shared from the phone ("text" packet): kdeconnectd itself puts it
            on the clipboard and says so ("Shared text from ... copied to
            clipboard", with Open Link when it is a link). Nothing to add.
  links     shared from the phone ("url" packet): kdeconnectd opens them in
            the browser at once and emits shareReceived(url); the watcher then
            also puts the link on the clipboard, with a notification (click:
            open it). KDE Connect's opening it cannot be switched off here.
  files     kdeconnectd saves them in its download folder (~/Downloads unless
            set in KDE Connect's settings) and emits shareReceived(file URL);
            the watcher moves photos and videos (PHOTO_EXT) into PHOTOS
            (~/Pictures/Phone), with a notification (click: open it).
            kdeconnectd's own "file received" note still names the old path.
  codes     the phone's notifications (the notifications plugin, which posts
            them on the desktop anyway): notificationPosted / Updated, read
            back from D-Bus. When one reads like a sign-in code (find_code:
            a code word -- code, OTP, verification, código, clave... -- and
            4..8 digits), a notification offers it (click: Copy; it shows
            only the last two digits, and silent re-sends of old
            notifications on reconnecting are not offered). The code
            goes on the clipboard marked sensitive (wl-copy --sensitive:
            cliphist 0.6+ does not store it, so it is never in the clipboard
            history) and is cleared after CODE_CLEAR_S if it is still there.
            It is never written to a log line or a file -- the service's
            log says "offered a sign-in code from <app>", no more. SMS arrive the same way: the phone's
            messaging app posts a notification; KDE Connect's SMS plugin
            itself (conversations) is not read.

Desktop -> phone, the page in the browser: the window title has the page
title, never the address, so tab_url() finds the title in the browser's own
session file: Firefox's sessionstore-backups/recovery.jsonlz4 (mozLz4, a
plain LZ4 block -- decoded here, no lz4 module needed; written every 15 s),
Chromium-family "Sessions/Session_*" files (SNSS: the UpdateTabNavigation
records carry url and title; written within seconds). Nothing is kept: the
files are read, the one matching address used. A private window has no
session entry and its title says so: refused. When no match is found (a
page opened seconds ago, an unknown browser) it says so and suggests the
clipboard (Ctrl+L, Ctrl+C, then "send the clipboard") -- it never types
into your window to copy the address itself.
"""
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import threading
import time
import urllib.parse

CLI = "kdeconnect-cli"
HERE = os.path.dirname(os.path.abspath(__file__))
NOTIFY = os.path.join(HERE, "notify")  # notify-send with the theme's mascot (mascot_notify.py)
HOME = os.path.expanduser("~")
PHOTOS = os.path.join(HOME, "Pictures", "Phone")
PHOTO_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".gif", ".dng", ".avif",
             ".mp4", ".mov", ".3gp", ".webm", ".mkv"}
CODE_CLEAR_S = 60
BUS_NAME = "org.kde.kdeconnect"
DAEMON_IFACE = "org.kde.kdeconnect.daemon"
DEVICE_IFACE = "org.kde.kdeconnect.device"
BATTERY_IFACE = "org.kde.kdeconnect.device.battery"
REDRAW_DELAY_MS = 400
NOTIF_IFACE = "org.kde.kdeconnect.device.notifications"
SHARE_IFACE = "org.kde.kdeconnect.device.share"
BROWSERS = re.compile(r"firefox|librewolf|zen|waterfox|chrome|chromium|brave|vivaldi|edge|opera", re.I)
FILE_MANAGERS = re.compile(r"nautilus|thunar|dolphin|nemo|pcmanfm|caja|cosmic-files", re.I)
PRIVATE_TITLE = re.compile(r"private browsing|incognito|inprivate|navegación privada", re.I)
# Window-title tails the browsers add after the page's own title.
TITLE_TAILS = re.compile(r"\s+[—–-]\s+(Mozilla Firefox|Firefox|LibreWolf|Zen Browser|Waterfox|Google Chrome|"
                         r"Chromium|Brave|Vivaldi|Microsoft Edge|Opera)(\s+\(.*\))?(\s+Private Browsing)?$", re.I)
FIREFOX_ROOTS = ("~/.config/mozilla/firefox", "~/.mozilla/firefox", "~/.var/app/org.mozilla.firefox/.mozilla/firefox",
                 "~/.var/app/org.mozilla.firefox/config/mozilla/firefox", "~/.librewolf", "~/.zen")
CHROME_ROOTS = ("~/.config/google-chrome", "~/.var/app/com.google.Chrome/config/google-chrome",
                "~/.config/chromium", "~/.var/app/org.chromium.Chromium/config/chromium",
                "~/.config/BraveSoftware/Brave-Browser",
                "~/.var/app/com.brave.Browser/config/BraveSoftware/Brave-Browser",
                "~/.config/vivaldi", "~/.config/microsoft-edge")
SNSS_UPDATE_NAV = 6     # Chromium's kCommandUpdateTabNavigation
# A sign-in code: a word that says so, then the digits. Words in English and
# Spanish (the phone's languages); "G-123456" is Google's form.
CODE_WORDS = re.compile(r"\b(code|codes|otp|passcode|verification|verify|2fa|two[- ]factor|one[- ]time|"
                        r"security|login|log[- ]in|sign[- ]in|pin|token|authenticat\w*|"
                        r"c[oó]digo|clave|verificaci[oó]n|autenticaci[oó]n|seguridad|contrase[nñ]a|"
                        r"inicio de sesi[oó]n|acceso)\b", re.I)
# Not part of a bigger number: "1,500", "12.50", "12:30", "#123456", "555-123-4567"
# are left alone, but a code may end a sentence ("is 849204.") or follow a
# colon ("code:849204").
CODE = re.compile(r"(?:(?<=\bG-)|(?<![\w.,/$€#-])(?<!\d:))(\d{3}[ -]\d{3}|\d{4,8})(?![\w/%$€-]|[.,:]\d)")
# What a password manager puts next to a copied secret (KeePassXC: wl-paste
# then says CLIPBOARD_STATE=sensitive): such a clipboard is never sent.
SECRET_TYPE = "x-kde-passwordManagerHint"


def run(*args, timeout=10):
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return out.stdout if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def bus_call(path, iface, method, signature="", *args, autostart=True):
    """kdeconnectd over D-Bus (busctl --json=short): the reply's data list,
    or None (no daemon, no such object, an error). autostart=False never
    starts kdeconnectd just to ask it something (the bar)."""
    argv = ["busctl", "--user", "--json=short", f"--auto-start={'yes' if autostart else 'no'}",
            "call", BUS_NAME, path, iface, method]
    if signature:
        argv += [signature, *args]
    out = run(*argv, timeout=3)
    try:
        return json.loads(out)["data"] if out else None
    except (ValueError, KeyError, TypeError):
        return None


def device_names(reachable_only, autostart=True):
    """{id: name} of the paired devices (only the reachable ones if asked)."""
    data = bus_call("/modules/kdeconnect", "org.kde.kdeconnect.daemon", "deviceNames", "bb",
                    "true" if reachable_only else "false", "true", autostart=autostart)
    return data[0] if data and isinstance(data[0], dict) else {}


def devices():
    """[{id, name, reachable}] of paired devices."""
    paired = device_names(False)
    live = device_names(True) if paired else {}
    return [{"id": i, "name": n, "reachable": i in live} for i, n in paired.items()]


def phone(autostart=True):
    live = device_names(True, autostart=autostart)
    return next(({"id": i, "name": n, "reachable": True} for i, n in live.items()), None)


def unvariant(value):
    """busctl's JSON for a variant ({"type": "i", "data": 80}) -> 80."""
    return value.get("data") if isinstance(value, dict) and "type" in value else value


def battery_reading(props):
    """(percent or None, charging) from the battery plugin's GetAll."""
    props = {k: unvariant(v) for k, v in (props or {}).items()}
    charge = props.get("charge")
    if isinstance(charge, bool) or not isinstance(charge, int) or charge < 0:
        return None, bool(props.get("isCharging"))
    return charge, bool(props.get("isCharging"))


def battery(device, autostart=True):
    data = bus_call(f"/modules/kdeconnect/devices/{device}/battery", "org.freedesktop.DBus.Properties",
                    "GetAll", "s", "org.kde.kdeconnect.device.battery", autostart=autostart)
    return battery_reading(data[0] if data else None)


BAR_HINT = "Click: Settings › Devices · Middle-click: ring it · Right-click: send the clipboard"


def bar_json(device, pct, charging):
    """custom/phone's line (it has no panel, so its tooltip is on). Ringing
    is the middle click: a ringing phone in a meeting is the one action here
    that should never come from a stray left click."""
    if not device:
        return {"text": "", "class": "none"}
    text = "\uf3cd" + (f" {pct}%" if pct is not None else "")
    return {"text": text, "class": "charging" if charging else ("low" if pct is not None and pct < 20 else "ok"),
            "tooltip": device["name"] + (f" · battery {pct}%{' (charging)' if charging else ''}"
                                         if pct is not None else "") + "\n\n" + BAR_HINT}


def need_phone():
    p = phone()
    if not p:
        subprocess.run([NOTIFY, "-a", "Phone", "-i", "phone", "No phone reachable",
                        "Is KDE Connect open on the phone, on the same network?"])
        sys.exit(1)
    return p


def notify(summary, body="", urgency="low", icon="phone"):
    subprocess.run([NOTIFY, "-a", "Phone", "-u", urgency, "-i", icon, summary, body])


def share(device, target):
    """kdeconnect-cli --share a file path or a URL (a URL opens on the phone)."""
    return run(CLI, "-d", device["id"], "--share", target, timeout=60) is not None


# -- desktop -> phone: the page in the browser ----------------------------------------
def lz4_block(src):
    """A raw LZ4 block, decoded (what mozLz4 wraps). Pure Python: ~40 ms for
    a session store of a few hundred kB."""
    dst, i, n = bytearray(), 0, len(src)
    while i < n:
        token = src[i]
        i += 1
        lit = token >> 4
        if lit == 15:
            while True:
                b = src[i]
                i += 1
                lit += b
                if b != 255:
                    break
        dst += src[i:i + lit]
        i += lit
        if i >= n:
            break
        offset = src[i] | (src[i + 1] << 8)
        i += 2
        length = token & 15
        if length == 15:
            while True:
                b = src[i]
                i += 1
                length += b
                if b != 255:
                    break
        start = len(dst) - offset
        if offset == 0 or start < 0:
            raise ValueError("bad LZ4 offset")
        for k in range(length + 4):        # may overlap what it copies: byte by byte
            dst.append(dst[start + k])
    return bytes(dst)


def mozlz4(data):
    if data[:8] != b"mozLz40\0":
        raise ValueError("not a mozLz4 file")
    return lz4_block(data[12:])


def firefox_tabs(path):
    """[(title, url)] of the current entry of every tab in a recovery.jsonlz4."""
    with open(path, "rb") as handle:
        store = json.loads(mozlz4(handle.read()))
    out = []
    for win in store.get("windows", []):
        for tab in win.get("tabs", []):
            entries = tab.get("entries") or []
            if entries:
                entry = entries[max(1, min(len(entries), tab.get("index", len(entries)))) - 1]
                out.append((entry.get("title", ""), entry.get("url", "")))
    return out


def snss_navigations(data):
    """[(title, url)] from a Chromium SNSS session file, oldest first: its
    UpdateTabNavigation records (a Pickle: size, tab id, index, url as
    length + UTF-8 padded to 4, title as length + UTF-16)."""
    if data[:4] != b"SNSS":
        return []
    pos, out = 8, []
    while pos + 2 <= len(data):
        size, = struct.unpack_from("<H", data, pos)
        pos += 2
        if size == 0 or pos + size > len(data):
            break
        cmd, body = data[pos], data[pos + 1:pos + size]
        pos += size
        if cmd != SNSS_UPDATE_NAV or len(body) < 20:
            continue
        try:
            p = 12                      # pickle size, tab id, index
            n, = struct.unpack_from("<i", body, p)
            p += 4
            if not 0 < n < len(body):
                continue
            url = body[p:p + n].decode("utf-8", "replace")
            p += (n + 3) & ~3
            m, = struct.unpack_from("<i", body, p)
            p += 4
            title = body[p:p + 2 * m].decode("utf-16-le", "replace") if 0 <= m < len(body) else ""
        except (struct.error, ValueError):
            continue
        out.append((title, url))
    return out


def page_title(window_title):
    """The page's own title in a browser window's title."""
    return TITLE_TAILS.sub("", window_title or "").strip()


def match_url(title, pairs):
    """The URL of the newest (last) entry whose title is `title`."""
    for t, url in reversed(pairs):
        if t.strip() == title and url.startswith(("http://", "https://", "ftp://")):   # not file://: a path here
            return url
    return None


def session_files(cls):
    """The session files to look in for a browser window class, newest first."""
    import glob
    if re.search(r"firefox|librewolf|zen|waterfox", cls, re.I):
        found = [f for root in FIREFOX_ROOTS
                 for f in glob.glob(os.path.join(os.path.expanduser(root), "*", "sessionstore-backups",
                                                 "recovery.jsonlz4"))]
    else:
        found = [f for root in CHROME_ROOTS
                 for f in glob.glob(os.path.join(os.path.expanduser(root), "*", "Sessions", "Session_*"))]
    return sorted(found, key=lambda f: -os.path.getmtime(f))


def url_from_sessions(cls, title):
    for path in session_files(cls)[:6]:
        try:
            if path.endswith(".jsonlz4"):
                pairs = firefox_tabs(path)
            else:
                with open(path, "rb") as handle:
                    pairs = snss_navigations(handle.read())
        except (OSError, ValueError, IndexError):
            continue
        url = match_url(title, pairs)
        if url:
            return url
    return None


def last_window(pattern):
    """The most recently focused window whose class matches `pattern`
    (Hyprland's focusHistoryID: 0 is the focused one), or None. Started from
    the launcher, the launcher is gone by then, so this is the browser you
    were just in."""
    try:
        clients = json.loads(run("hyprctl", "clients", "-j", timeout=3) or "[]")
    except ValueError:
        return None
    hits = [c for c in clients if pattern.search(c.get("class") or "")]
    return min(hits, key=lambda c: c.get("focusHistoryID", 99)) if hits else None


PRIVATE_WHY = "That is a private window: its address is not sent."


def tab_url():
    """(url, None) for the page in the browser used last, else (None, why)."""
    win = last_window(BROWSERS)
    if not win:
        return None, "No browser window is open."
    title = win.get("title") or ""
    if PRIVATE_TITLE.search(title):
        return None, PRIVATE_WHY
    m = re.search(r"https?://\S+", title)
    if m:
        return m[0], None
    url = url_from_sessions(win["class"], page_title(title))
    if url:
        return url, None
    return None, ("Could not find that page's address in the browser's session file (a page opened a "
                  "few seconds ago is not saved yet). Copy it (Ctrl+L, Ctrl+C) and send the clipboard.")


def clipboard_text():
    return run("wl-paste", "--no-newline", "--type", "text", timeout=3) or ""


def clipboard_secret():
    """Did a password manager copy what is on the clipboard (SECRET_TYPE)?"""
    return SECRET_TYPE in (run("wl-paste", "--list-types", timeout=3) or "").split()


def open_on_phone(target=None, tab_only=False):
    why = ""
    if not target:
        target, why = tab_url()
        # A private window refused is not a reason to send some other link instead.
        if not target and not tab_only and why != PRIVATE_WHY:
            clip = "" if clipboard_secret() else clipboard_text().strip()
            if re.fullmatch(r"https?://\S+", clip):
                target, why = clip, None
        if not target:
            notify("Nothing to open on the phone", why, "normal")
            return 1
    p = need_phone()
    if share(p, target):
        notify(f"Opened on {p['name']}", target[:120])
        return 0
    notify("The phone did not take it", target[:120], "normal")
    return 1


# -- desktop -> phone: files --------------------------------------------------------------
def uri_paths(text):
    """The local files in a text/uri-list."""
    return [urllib.parse.unquote(urllib.parse.urlparse(u.strip()).path)
            for u in (text or "").splitlines() if u.strip().startswith("file://")]


def copied_files():
    """Paths copied in a file manager (text/uri-list on the clipboard)."""
    types = (run("wl-paste", "--list-types", timeout=3) or "").split()
    if "text/uri-list" not in types:
        return []
    text = run("wl-paste", "--no-newline", "--type", "text/uri-list", timeout=3) or ""
    return [p for p in uri_paths(text) if os.path.isfile(p)]


def pick_files():
    """A zenity picker, in the folder of the file manager used last (its
    title, read the way sessions.py's title_path does), else ~."""
    start = HOME
    win = last_window(FILE_MANAGERS)
    if win:
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("sessions", os.path.join(HERE, "sessions.py"))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            start = mod.title_path(win.get("title")) or HOME
        except Exception:       # the picker still opens, in ~
            pass
    if not shutil.which("zenity"):
        notify("No file picker", "zenity is not installed (sudo dnf install zenity)", "normal")
        return []
    out = run("zenity", "--file-selection", "--multiple", "--separator=\n", "--title=Send to the phone",
              f"--filename={start.rstrip('/')}/", timeout=3600) or ""
    return [p for p in out.splitlines() if os.path.isfile(p)]


def send_files(paths):
    if not paths:
        return 1
    p = need_phone()
    sent = [path for path in paths if share(p, os.path.abspath(path))]
    if sent:
        notify(f"Sent to {p['name']}", ", ".join(os.path.basename(a) for a in sent)[:200])
    if len(sent) < len(paths):
        notify("Some files were not sent", ", ".join(os.path.basename(a) for a in paths if a not in sent)[:200],
               "normal")
    return 0 if sent else 1


# -- phone -> desktop: the watcher --------------------------------------------------------
def find_code(text):
    """The sign-in code in a notification's text, or None. Needs a code word
    (CODE_WORDS) and 4..8 digits (or 123-456); a year-looking number loses
    to any other candidate, a six-digit one wins over the rest."""
    if not text or not CODE_WORDS.search(text):
        return None
    found = [m[1].replace(" ", "").replace("-", "") for m in CODE.finditer(text)]
    if not found:
        return None

    def rank(code):
        yearish = len(code) == 4 and code[:2] in ("19", "20")
        return (yearish, len(code) != 6)
    return sorted(found, key=rank)[0]


def privacy():
    if HERE not in sys.path:    # once: codes_on() runs at every phone notification
        sys.path.insert(0, HERE)
    import privacy_settings
    return privacy_settings


def codes_on():
    try:
        ps = privacy()
        return ps.phone_codes_on(ps.load())
    except Exception:           # unreadable settings: the shipped default, off
        return False


def set_codes(on):
    privacy_settings = privacy()
    privacy_settings.set_key("phone_codes", "on" if on else "off")


def unique_path(folder, name):
    base, ext = os.path.splitext(name)
    path, n = os.path.join(folder, name), 2
    while os.path.exists(path):
        path = os.path.join(folder, f"{base} ({n}){ext}")
        n += 1
    return path


def is_photo(path):
    return os.path.splitext(path)[1].lower() in PHOTO_EXT


def ask(summary, body, actions, timeout=600):
    """A notification with buttons (mako: "default" is the click); the key of
    the one picked, or "". -e: transient, not kept in the history."""
    argv = [NOTIFY, "-a", "Phone", "-i", "phone", "--wait", "-e"]
    for key, label in actions:
        argv += ["-A", f"{key}={label}"]
    try:
        return subprocess.run(argv + [summary, body], capture_output=True, text=True,
                              timeout=timeout).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def copy(text, sensitive=False):
    argv = ["wl-copy"] + (["--sensitive"] if sensitive else []) + ["--", text]
    try:
        subprocess.run(argv, timeout=5, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        pass


def clear_if_still(code):
    """CODE_CLEAR_S after a code was copied: off the clipboard, unless
    something else was copied meanwhile."""
    if clipboard_text().strip() == code:
        run("wl-copy", "--clear", timeout=5)


def xdg_open(*argv):
    subprocess.Popen(list(argv), start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def log(text):
    print(f"phone: {text}", flush=True)


def poke_bar():
    """Redraw custom/phone (bar_signals.py has the number)."""
    try:
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        import bar_signals
        bar_signals.poke("phone")
    except Exception as err:   # no bar is not the watcher's problem
        log(f"could not redraw the bar pill: {err}")


class Watcher:
    """phone.py watch: kdeconnectd's signals -> what the docstring says.
    Each signal's work runs in a thread of its own (a notification waiting
    for its click must not hold the next one)."""

    def __init__(self):
        from gi.repository import Gio
        self.Gio = Gio
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.offered = {}           # code -> when: an update of the same notification is not offered again
        self.lock = threading.Lock()

    def start(self):
        flags = self.Gio.DBusSignalFlags.NONE
        self.bus.signal_subscribe(BUS_NAME, SHARE_IFACE, "shareReceived", None, None, flags, self.on_share)
        for member in ("notificationPosted", "notificationUpdated"):
            self.bus.signal_subscribe(BUS_NAME, NOTIF_IFACE, member, None, None, flags, self.on_notification)
        # The bar pill: a phone coming or going, pairing, the battery, and
        # kdeconnectd itself starting or stopping. member None = all of the
        # interface's signals.
        for iface, member in ((DAEMON_IFACE, None), (DEVICE_IFACE, None), (BATTERY_IFACE, None)):
            self.bus.signal_subscribe(BUS_NAME, iface, member, None, None, flags, self.on_device)
        self.bus.signal_subscribe("org.freedesktop.DBus", "org.freedesktop.DBus", "NameOwnerChanged",
                                  "/org/freedesktop/DBus", BUS_NAME, flags, self.on_device)
        self.redraw_pending = False

    # -- the bar pill
    def on_device(self, *_args):
        """Coalesce a burst (a reconnect sends visibility, reachable and a
        battery refresh within milliseconds) into one redraw."""
        from gi.repository import GLib
        if not getattr(self, "redraw_pending", False):
            self.redraw_pending = True
            GLib.timeout_add(REDRAW_DELAY_MS, self.redraw_bar)

    def redraw_bar(self):
        self.redraw_pending = False
        poke_bar()
        return False

    @staticmethod
    def background(work, *args):
        threading.Thread(target=work, args=args, daemon=True).start()

    # -- files and links
    def on_share(self, _bus, _sender, _path, _iface, _member, params):
        url = params.unpack()[0] if params else ""
        self.background(self.received, url)

    def received(self, url):
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme == "file":
            path = urllib.parse.unquote(parsed.path)
            if not is_photo(path):
                return          # kdeconnectd's own notification covers other files
            dest = move_photo(path)
            if not dest:
                return
            if ask("Photo from the phone", f"{os.path.basename(dest)}, in ~/Pictures/Phone",
                   [("default", "Open")]) == "default":
                xdg_open("xdg-open", dest)
        elif parsed.scheme in ("http", "https"):
            copy(url)
            log("a link from the phone, put on the clipboard")
            if ask("Link from the phone", f"{url[:160]}\nOn the clipboard. Click to open it (KDE Connect "
                   "may have opened it already).", [("default", "Open")]) == "default":
                xdg_open("xdg-open", url)

    # -- 2FA codes
    def on_notification(self, _bus, _sender, path, _iface, _member, params):
        if not codes_on():
            return
        public_id = params.unpack()[0] if params else ""
        if public_id:
            self.background(self.check_code, f"{path}/{public_id}")

    def props(self, path):
        from gi.repository import GLib
        try:
            reply = self.bus.call_sync(BUS_NAME, path, "org.freedesktop.DBus.Properties", "GetAll",
                                       GLib.Variant("(s)", (NOTIF_IFACE + ".notification",)), None,
                                       self.Gio.DBusCallFlags.NONE, 3000, None)
            return reply.unpack()[0]
        except Exception:       # gone already, or an older kdeconnectd
            return {}

    def check_code(self, path):
        p = self.props(path)
        if p.get("silent"):
            # What the phone re-sends on (re)connecting comes silent: old
            # notifications, whose codes are stale -- not offered again.
            return
        code = find_code(" ".join(str(p.get(k) or "") for k in ("title", "text", "ticker")))
        if not code:
            return
        now = time.time()
        with self.lock:
            self.offered = {c: t for c, t in self.offered.items() if now - t < 300}
            if code in self.offered:
                return
            self.offered[code] = now
        offer_code(code, str(p.get("appName") or "the phone"))


def move_photo(path):
    """A received photo or video into PHOTOS; its new path, or None."""
    for _ in range(20):         # the job can report a moment before the file is in place
        if os.path.isfile(path):
            break
        time.sleep(0.5)
    try:
        os.makedirs(PHOTOS, exist_ok=True)
        dest = unique_path(PHOTOS, os.path.basename(path))
        shutil.move(path, dest)
    except OSError as err:
        log(f"could not move a received photo: {err}")
        return None
    log(f"a photo from the phone, moved to {PHOTOS}")
    return dest


def masked(code):
    """'482913' -> '••••13': what the offer shows. mako keeps expired
    notifications in its history (notify-digest reads it), so the whole
    code is not written there a second time."""
    return "•" * (len(code) - 2) + code[-2:]


def offer_code(code, app):
    """The one-click Copy for a sign-in code. Logged without the code."""
    log(f"offered a sign-in code from {app}")
    if ask(f"Sign-in code from {app}", f"{masked(code)}\nClick to copy it: on the clipboard for {CODE_CLEAR_S} s, "
           "never in the clipboard history.", [("default", "Copy")], timeout=300) == "default":
        copy(code, sensitive=True)
        threading.Timer(CODE_CLEAR_S, clear_if_still, args=(code,)).start()


def watch():
    from gi.repository import GLib
    Watcher().start()
    log(f"watching KDE Connect (photos -> {PHOTOS}; sign-in codes {'on' if codes_on() else 'off'})")
    GLib.MainLoop().run()


def status():
    """What the handoff can do now (Settings > Devices)."""
    cli = shutil.which(CLI) is not None
    p = phone() if cli else None
    unit = (run("systemctl", "--user", "is-active", "phone-handoff.service", timeout=5) or "").strip()
    plugins = {}
    if p:
        out = run("gdbus", "call", "--session", "--dest", BUS_NAME, "--object-path",
                  f"/modules/kdeconnect/devices/{p['id']}", "--method",
                  "org.kde.kdeconnect.device.loadedPlugins", timeout=3) or ""
        plugins = {k: f"kdeconnect_{k}" in out for k in ("share", "notifications", "clipboard", "sms")}
    return {"kdeconnect": cli, "phone": p["name"] if p else "", "watcher": unit == "active",
            "codes": codes_on(), "plugins": plugins, "photos": PHOTOS, "picker": bool(shutil.which("zenity"))}


def main(argv):
    cmd = argv[0] if argv else "list"
    if cmd == "bar":
        p = phone(autostart=False)
        pct, charging = battery(p["id"], autostart=False) if p else (None, False)
        print(json.dumps(bar_json(p, pct, charging)))
    elif cmd == "ring":
        run(CLI, "-d", need_phone()["id"], "--ring")
    elif cmd == "ping":
        run(CLI, "-d", need_phone()["id"], "--ping-msg", "Hello from the desktop")
    elif cmd == "share" and len(argv) > 1:
        p = need_phone()
        for path in argv[1:]:
            run(CLI, "-d", p["id"], "--share", os.path.abspath(path), timeout=60)
        subprocess.run([NOTIFY, "-a", "Phone", "-u", "low", "-i", "phone",
                        f"Sent to {p['name']}", ", ".join(os.path.basename(a) for a in argv[1:])])
    elif cmd == "clip":
        p = need_phone()
        if clipboard_secret():
            notify("Not sent", "The clipboard holds a password manager's secret.", "normal")
            sys.exit(1)
        text = run("wl-paste", "--no-newline", "--type", "text") or ""
        if text:
            run(CLI, "-d", p["id"], "--share-text", text)
            subprocess.run([NOTIFY, "-a", "Phone", "-u", "low", "-i", "phone",
                            f"Clipboard sent to {p['name']}"])
    elif cmd == "open":
        sys.exit(open_on_phone(argv[1] if len(argv) > 1 else None))
    elif cmd == "tab":
        if "--print" in argv:
            url, why = tab_url()
            print(url or why)
            sys.exit(0 if url else 1)
        sys.exit(open_on_phone(tab_only=True))
    elif cmd == "file":
        if "--copied" in argv:
            paths = copied_files()
            if not paths:
                notify("No files copied", "Select files in Files, press Ctrl+C, then send again.", "normal")
                sys.exit(1)
        else:
            if not argv[1:]:
                need_phone()        # before the picker: no choosing files for a phone that is away
            paths = argv[1:] or pick_files()
        sys.exit(send_files(paths))
    elif cmd == "watch":
        watch()
    elif cmd == "codes" and argv[1:2] in (["on"], ["off"]):
        set_codes(argv[1] == "on")
    elif cmd == "status":
        data = status()
        print(json.dumps(data) if "--json" in argv else
              "\n".join(f"{k}: {v}" for k, v in data.items()))
    elif cmd == "list":
        rows = devices()
        print(json.dumps(rows) if "--json" in argv else
              "\n".join(f"{d['name']}  ({'reachable' if d['reachable'] else 'away'})" for d in rows) or "none paired")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
