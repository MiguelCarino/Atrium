"""Settings page: Machines -- your other computers as one desktop, peer to
peer on the local network (peers.py; its docstring has the pairing, the
encryption and every rule about what is sent).

    THIS MACHINE        its name as the others show it, the master switch,
                        its id and where it listens (folded) (off until a machine
                        is paired: pairing turns it on)
    PAIRED MACHINES     each one: last seen where, Ping, Send my windows /
                        Get its windows (an offer on the other side, never a
                        restore), Forget (asks once more)
    PAIR A MACHINE      "Show a code" here and "Join" there (or the other way
                        round): both screens show the same 6 digits, and
                        "The codes match" on both pairs them
    WHAT IS SHARED      clipboard (OFF as shipped; privacy.conf), project
                        context (off / ask / auto), sessions, files and links
                        (links ask / open, the size limit), desktop memory
                        (OFF as shipped; privacy.conf)
    WAKE-ON-LAN         a Wake button on every paired machine whose MAC is
                        known (learnt from this computer's neighbour table
                        while it is up: wol.py learn), and other machines
                        by name and MAC (wol.py add / send / remove)
    SHARED KEYBOARD AND MOUSE   lan-mouse: Install (the pinned release), on /
                        off, and which side each machine's screen is on

Nothing is kept here: every control runs peers.py (set, name, clipboard,
memory, unpair, ping, session, kvm), and the page redraws from `peers.py
status --json`, which never touches the network. A pairing runs `peers.py
pair|join --json` as a child: its events (waiting, code, paired, rejected,
error) come on its stdout, and the page answers "yes" / "no" on its stdin.
"""
from .common import *  # noqa: F401,F403  (the shared helpers and paths; Gtk 3)

from gi.repository import GLib, Gtk  # noqa: E402,F401

import json  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

PAGE = {"id": "machines", "title": "Machines", "icon": "", "group": "Hardware", "order": 95, "parent": "devices", "tab": "Machines",
        "keywords": ["other computer", "laptop", "pair", "peer", "lan", "multi machine", "share clipboard",
                     "send to computer", "send window", "keyboard and mouse", "kvm", "lan-mouse", "barrier",
                     "synergy", "input leap", "computadora", "otra máquina", "emparejar", "portapapeles",
                     "wake on lan", "wol", "magic packet", "turn on remotely", "encender"]}

PEERS = os.path.join(HYPR, "peers.py")
WOL = os.path.join(HYPR, "wol.py")
CONTEXT = [("off", "Off"), ("ask", "Ask"), ("auto", "Follow")]
LINKS = [("ask", "Ask"), ("open", "Open at once")]
SIZES = [("100", "100 MB"), ("500", "500 MB"), ("2000", "2 GB")]
SIDES = [("left", "Left"), ("right", "Right"), ("top", "Above"), ("bottom", "Below")]
SWITCHES = [
    ("clipboard", "\uf0ea", "Share the clipboard",
     "copied text both ways, never passwords or keys  ·  both sides need it on"),
    ("sessions", "\uf2d2", "Sessions",
     "send or get windows; the other side gets a Restore button"),
    ("send", "\uf019", "Receive files and links",
     "pages, files and links  ·  files land in ~/Downloads"),
    ("memory", "\uf1da", "Let them ask this machine's desktop memory",
     "a paired machine may ask; only the answer goes back"),
]


# -- pure helpers (tests/test_peers.py) ------------------------------------------------------
def seen_text(peer, now=None):
    """"seen 2 min ago at 192.168.0.12 · AB12-CD34"."""
    now = now if now is not None else time.time()
    if peer.get("seen"):
        ago = max(0, int(now - peer["seen"]))
        when = "seen just now" if ago < 60 else f"seen {ago // 60} min ago" if ago < 3600 else \
            f"seen {ago // 3600} h ago" if ago < 86400 else "seen " + time.strftime("%d %b", time.localtime(peer["seen"]))
    else:
        when = "not seen since pairing"
    where = f" at {peer['host']}" if peer.get("host") else ""
    return f"{when}{where}  ·  {peer.get('short', '')}"


def machine_text(data):
    """The line under this machine's name."""
    parts = [f"id {data['id']}" if data.get("id") else "no identity yet (made at the first pairing)"]
    if data.get("addresses"):
        parts.append(", ".join(data["addresses"]) + f" port {data.get('port')}")
    service = data.get("service") or ""
    if data.get("peers"):
        parts.append("sharing" if data.get("enabled") and service.startswith("active") else
                     "switched off" if not data.get("enabled") else f"the service is {service}")
    return "  ·  ".join(parts)


def wake_entry(machines, peer):
    """wol.py's saved machine for a paired one (by peer id, else by name), or None."""
    found = next((m for m in machines if m.get("peer") and m["peer"] == peer.get("id")), None)
    return found or next((m for m in machines if not m.get("peer")
                          and str(m.get("name", "")).lower() == str(peer.get("name", "")).lower()), None)


def other_machines(machines, peers):
    """The saved Wake-on-LAN machines that are not one of the paired ones."""
    mine = [wake_entry(machines, p) for p in peers]
    return [m for m in machines if not any(m is x for x in mine)]


def kvm_text(kvm):
    if not kvm.get("installed"):
        return f"lan-mouse {kvm.get('pinned')} is not installed"
    return ("on  ·  cross at the screen edge, Ctrl+Shift+Super+Alt comes back" if kvm.get("on") else "off")


def kvm_details(kvm):
    """The kvm fold's text: what Install does, or the version and service."""
    if not kvm.get("installed"):
        return ("Install fetches lan-mouse's release from GitHub (checked against a fixed checksum) into "
                "~/.local/share/peers; nothing system-wide changes.")
    return (f"lan-mouse {kvm.get('version') or '?'} ({kvm.get('service')}), its own encrypted link. Move the "
            "pointer past the edge set below to cross over.")


class Page:
    def __init__(self):
        self.widget = page_box()
        w = self.widget
        self.updating = False
        self.data = {}
        self.proc = None            # a running pair / join
        self.armed = None           # the machine whose Forget was clicked once
        self.learning = set()       # peers whose MAC was looked for this time
        self.asking = False         # a code is shown and this side has not answered yet

        w.pack_start(heading("THIS MACHINE"), False, False, 0)
        box = Gtk.Box(spacing=8)
        self.name = Gtk.Entry()
        self.name.set_hexpand(True)
        self.name.set_max_length(32)
        self.name.connect("activate", lambda _e: self.rename())
        box.pack_start(self.name, True, True, 0)
        box.pack_start(link("Rename", self.rename), False, False, 0)
        w.pack_start(box, False, False, 0)
        self.master = Gtk.Switch()
        self.master.connect("state-set", lambda _s, on: self.set("enabled", "on" if on else "off"))
        grid, self.master_sub = row("\uf0e8", "Share with the paired machines", "", self.master)
        w.pack_start(grid, False, False, 0)
        self.me = dp.label("", "ctl-sub")
        self.me.set_line_wrap(True)
        self.me.set_selectable(True)
        w.pack_start(details(self.me), False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("PAIRED MACHINES"), False, False, 0)
        self.rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        w.pack_start(self.rows, False, False, 0)
        self.result = dp.label("", "ctl-sub")
        self.result.set_line_wrap(True)
        w.pack_start(self.result, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("WAKE-ON-LAN"), False, False, 0)
        self.wol_rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        w.pack_start(self.wol_rows, False, False, 0)
        box = Gtk.Box(spacing=8)
        self.wol_name = Gtk.Entry()
        self.wol_name.set_placeholder_text("name")
        self.wol_name.set_width_chars(12)
        self.wol_mac = Gtk.Entry()
        self.wol_mac.set_placeholder_text("MAC address, e.g. aa:bb:cc:dd:ee:ff")
        self.wol_mac.set_hexpand(True)
        self.wol_mac.connect("activate", lambda _e: self.wol_add())
        box.pack_start(self.wol_name, False, False, 0)
        box.pack_start(self.wol_mac, True, True, 0)
        box.pack_start(link("Remember", self.wol_add), False, False, 0)
        w.pack_start(box, False, False, 0)
        wol_more = dp.label("Wake sends the \"magic packet\" to the machine's network card on this network. "
                            "It must allow it: Wake on LAN on in its firmware setup, and on Linux "
                            "`nmcli connection modify <connection> 802-3-ethernet.wake-on-lan magic`. "
                            "Wired cards almost always can, Wi-Fi almost never. A paired machine's MAC is "
                            "picked up by itself while that machine is on.", "ctl-sub")
        wol_more.set_line_wrap(True)
        w.pack_start(details(wol_more), False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("PAIR A MACHINE"), False, False, 0)
        note = dp.label("Show a code on one machine, Join on the other, then confirm the digits match.",
                        "ctl-sub")
        note.set_line_wrap(True)
        w.pack_start(note, False, False, 0)
        box = Gtk.Box(spacing=8)
        self.address = Gtk.Entry()
        self.address.set_placeholder_text("address:port to join (empty: find it on this network)")
        self.address.set_hexpand(True)
        box.pack_start(self.address, True, True, 0)
        w.pack_start(box, False, False, 0)
        self.pair_links = links_row(link("Show a code", lambda: self.start("pair")),
                                    link("Join", lambda: self.start("join")))
        w.pack_start(self.pair_links, False, False, 0)
        self.code = Gtk.Label()
        self.code.set_selectable(True)
        w.pack_start(self.code, False, False, 0)
        self.pair_sub = dp.label("", "ctl-sub")
        self.pair_sub.set_line_wrap(True)
        w.pack_start(self.pair_sub, False, False, 0)
        self.answer = links_row(link("The codes match", lambda: self.reply("yes")),
                                link("They differ / Cancel", lambda: self.reply("no")))
        self.answer.set_no_show_all(True)
        w.pack_start(self.answer, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("WHAT IS SHARED"), False, False, 0)
        self.switches = {}
        for key, icon, title, sub in SWITCHES:
            sw = Gtk.Switch()
            sw.connect("state-set", lambda _s, on, k=key: self.flip(k, on))
            grid, _ = row(icon, title, sub, sw)
            self.switches[key] = sw
            w.pack_start(grid, False, False, 0)
        self.context = Chips(lambda key: self.set("context", key))
        grid, _ = row("\uf542", "Project context",
                      "entering a project here: Ask offers it there, Follow opens it there", None)
        w.pack_start(grid, False, False, 0)
        w.pack_start(self.context.widget, False, False, 0)
        self.links = Chips(lambda key: self.set("links", key))
        grid, _ = row("\uf0c1", "Links that arrive", "a notification with Open and Copy, or opened at once", None)
        w.pack_start(grid, False, False, 0)
        w.pack_start(self.links.widget, False, False, 0)
        self.sizes = Chips(lambda key: self.set("max_mb", key))
        grid, _ = row("\uf15b", "Largest file accepted", "bigger ones are refused", None)
        w.pack_start(grid, False, False, 0)
        w.pack_start(self.sizes.widget, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("SHARED KEYBOARD AND MOUSE"), False, False, 0)
        self.kvm = Gtk.Switch()
        self.kvm.connect("state-set", lambda _s, on: self.kvm_flip(on))
        grid, self.kvm_sub = row("\uf11c", "One keyboard and mouse for all the screens", "", self.kvm)
        w.pack_start(grid, False, False, 0)
        self.kvm_install = links_row(link("Install lan-mouse", self.install))
        self.kvm_install.set_no_show_all(True)
        w.pack_start(self.kvm_install, False, False, 0)
        self.sides = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        w.pack_start(self.sides, False, False, 0)
        self.kvm_more = dp.label("", "ctl-sub")
        self.kvm_more.set_line_wrap(True)
        w.pack_start(details(self.kvm_more), False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("KEYS"), False, False, 0)
        keys = dp.label("SUPER+ALT+M send this window  ·  SUPER+ALT+SHIFT+M send the clipboard  ·  "
                        "SUPER+ALT+SHIFT+K shared keyboard and mouse", "ctl-sub")
        keys.set_line_wrap(True)
        w.pack_start(keys, False, False, 0)

    # -- actions ----------------------------------------------------------------------------
    def rename(self):
        name = self.name.get_text().strip()
        if name and name != self.data.get("name"):
            background(lambda: run(PEERS, "name", name), lambda _o: self.refresh())

    def set(self, key, value):
        if not self.updating:
            background(lambda: run(PEERS, "set", key, value, timeout=30), lambda _o: self.refresh())
        return False

    def flip(self, key, on):
        if self.updating:
            return False
        value = "on" if on else "off"
        argv = (PEERS, key, value) if key in ("clipboard", "memory") else (PEERS, "set", key, value)
        background(lambda: run(*argv), lambda _o: self.refresh())
        return False

    def kvm_flip(self, on):
        if self.updating:
            return False
        self.kvm_sub.set_text("switching...")
        background(lambda: subprocess.run([PEERS, "kvm", "on" if on else "off"], capture_output=True, text=True,
                                          timeout=40),
                   lambda r: (self.kvm_sub.set_text((r.stdout or r.stderr).strip().removeprefix("peers: ")),
                              GLib.timeout_add(1500, lambda: (self.refresh(), False)[1])))
        return False

    def install(self):
        self.kvm_sub.set_text("downloading lan-mouse...")
        background(lambda: subprocess.run([PEERS, "kvm", "install"], capture_output=True, text=True, timeout=180),
                   lambda r: (self.kvm_sub.set_text((r.stdout or r.stderr).strip().removeprefix("peers: ")),
                              self.refresh()))

    def side(self, pid, side):
        if not self.updating:
            background(lambda: run(PEERS, "kvm", "side", pid, side, timeout=20),
                       lambda out: (self.result.set_text(out.strip()), self.refresh()))

    def peer_action(self, label, *argv, timeout=40):
        self.result.set_text(f"{label}...")
        background(lambda: subprocess.run([PEERS, *argv], capture_output=True, text=True, timeout=timeout),
                   lambda r: (self.result.set_text((r.stdout or r.stderr).strip().removeprefix("peers: ")
                                                   or f"{label}: done"), self.refresh()))

    def ping(self, peer):
        def done(r):
            try:
                got = json.loads(r.stdout or "[]")[0]
            except (ValueError, IndexError):
                got = {"ok": False, "why": (r.stderr or "no answer").strip()}
            if got.get("ok"):
                acc = got.get("accepts") or {}
                on = [k for k in ("clipboard", "sessions", "send", "memory") if acc.get(k)]
                self.result.set_text(f"{peer['name']} answered in {got['ms']} ms; it takes "
                                     + (", ".join(on) or "nothing yet") + f"; project context: {acc.get('context')}")
            else:
                self.result.set_text(got.get("why") or "no answer")
            self.refresh()
        self.result.set_text(f"asking {peer['name']}...")
        background(lambda: subprocess.run([PEERS, "ping", peer["id"], "--json"], capture_output=True, text=True,
                                          timeout=30), done)

    def forget(self, peer, button):
        if self.armed != peer["id"]:
            self.armed = peer["id"]
            button.set_label("Forget?")
            GLib.timeout_add(3000, lambda: (self.disarm(peer["id"], button), False)[1])
            return
        self.armed = None
        self.peer_action(f"forgetting {peer['name']}", "unpair", peer["id"])

    def wake(self, name):
        self.peer_action_wol(f"waking {name}", "send", name)

    def peer_action_wol(self, label, *argv):
        self.result.set_text(f"{label}...")
        background(lambda: subprocess.run([WOL, *argv], capture_output=True, text=True, timeout=15),
                   lambda r: (self.result.set_text((r.stdout or r.stderr).strip().removeprefix("wol: ")
                                                   or f"{label}: done"), self.refresh()))

    def wol_add(self):
        name, mac = self.wol_name.get_text().strip(), self.wol_mac.get_text().strip()
        if not name or not mac:
            self.result.set_text("Wake-on-LAN: a name and a MAC address")
            return
        self.wol_name.set_text("")
        self.wol_mac.set_text("")
        self.peer_action_wol(f"remembering {name}", "add", name, mac)

    def learn_macs(self, peers, machines):
        """Look up the MAC of paired machines seen at an address (the
        neighbour table, no packet sent), once per page."""
        for p in peers:
            if p.get("host") and p["id"] not in self.learning and not wake_entry(machines, p):
                self.learning.add(p["id"])
                background(lambda p=p: run(WOL, "learn", p["id"], p["host"], p["name"], timeout=10),
                           lambda out: out.strip() and self.refresh())

    def disarm(self, pid, button):
        if self.armed == pid:
            self.armed = None
            button.set_label("Forget")

    # -- pairing ----------------------------------------------------------------------------
    def start(self, mode):
        if self.proc and self.proc.poll() is None:
            return
        argv = [PEERS, mode, "--json"]
        if mode == "join" and self.address.get_text().strip():
            argv.insert(2, self.address.get_text().strip())
        self.code.set_text("")
        self.pair_sub.set_text("starting..." if mode == "pair" else "looking for the machine...")
        try:
            self.proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL, text=True)
        except OSError as exc:
            self.pair_sub.set_text(str(exc))
            return
        self.pair_links.set_sensitive(False)
        threading.Thread(target=self.follow, args=(self.proc,), daemon=True).start()

    def follow(self, proc):
        for line in proc.stdout:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            GLib.idle_add(lambda e=event: (self.on_event(e), False)[1])
        proc.wait()
        GLib.idle_add(lambda: (self.pair_done(), False)[1])

    def on_event(self, e):
        kind = e.get("event")
        if kind == "waiting":
            where = ", ".join(f"{a}:{e['port']}" for a in e.get("addresses") or []) or f"port {e['port']}"
            self.pair_sub.set_text(f"Waiting 3 min: press Join on the other machine, or type {where} there.")
        elif kind == "code":
            self.code.set_markup(f"<span size='xx-large' weight='bold'>{GLib.markup_escape_text(e['code'])}</span>")
            self.pair_sub.set_text(f"Is this the code on {e.get('peer')}'s screen too?")
            self.asking = True
            self.answer.set_no_show_all(False)
            self.answer.show_all()
        elif kind == "paired":
            self.code.set_text("")
            self.pair_sub.set_text(f"Paired with {e.get('peer')}.")
        elif kind in ("rejected", "timeout", "error"):
            self.code.set_text("")
            self.pair_sub.set_text(e.get("why") or kind)

    def reply(self, answer):
        self.asking = False
        self.answer.hide()
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.stdin.write(answer + "\n")
                self.proc.stdin.flush()
            except OSError:
                pass
            if answer == "no":
                GLib.timeout_add(1500, lambda: (self.proc and self.proc.poll() is None and self.proc.terminate(),
                                                False)[1])
        self.pair_sub.set_text("waiting for the other machine's answer..." if answer == "yes" else "cancelled")

    def pair_done(self):
        self.asking = False
        self.answer.hide()
        self.pair_links.set_sensitive(True)
        self.refresh()

    # -- drawing ----------------------------------------------------------------------------
    def refresh(self):
        def work():
            data = run_json(PEERS, "status", "--json") or {}
            if data:
                data["wol"] = (run_json(WOL, "list", "--json", timeout=5) or {}).get("machines") or []
            return data
        background(work, self.draw)

    def draw(self, data):
        if not data:
            self.master_sub.set_text("could not read the status")
            return
        self.data = data
        self.updating = True
        if not self.name.has_focus():
            self.name.set_text(data.get("name") or "")
        self.me.set_text(machine_text(data))
        peers = data.get("peers") or []
        self.master.set_active(bool(data.get("enabled")))
        self.master.set_sensitive(bool(peers))
        self.master_sub.set_text("turns on when a machine is paired" if not peers else
                                 "off: nothing shared; the pairings stay" if not data.get("enabled")
                                 else "on, for the paired machines only")
        clear(self.rows)
        machines = data.get("wol") or []
        for p in peers:
            forget = Gtk.Button(label="Forget")
            forget.get_style_context().add_class("ctl-link")
            forget.connect("clicked", lambda b, peer=p: self.forget(peer, b))
            woke = wake_entry(machines, p)
            wake = [link("Wake", lambda m=woke: self.wake(m["name"]))] if woke else []
            grid, _ = row("\uf109", p["name"], seen_text(p), links_row(
                *wake,
                link("Ping", lambda peer=p: self.ping(peer)),
                link("Send my windows", lambda peer=p: self.peer_action("offering your windows", "session", "send",
                                                                         "--to", peer["id"])),
                link("Get its windows", lambda peer=p: self.peer_action("asking for its windows", "session", "get",
                                                                         "--to", peer["id"], timeout=200)),
                forget))
            self.rows.pack_start(grid, False, False, 0)
        if not peers:
            self.rows.pack_start(dp.label("None yet: pair one below.", "ctl-sub"), False, False, 0)
        clear(self.wol_rows)
        for m in other_machines(machines, peers):
            grid, _ = row("\uf011", m["name"], m["mac"], links_row(
                link("Wake", lambda name=m["name"]: self.wake(name)),
                link("Remove", lambda name=m["name"]: self.peer_action_wol(f"forgetting {name}", "remove", name))))
            self.wol_rows.pack_start(grid, False, False, 0)
        self.learn_macs(peers, machines)
        f = data.get("features") or {}
        for key, sw in self.switches.items():
            sw.set_active(bool(f.get(key)))
        self.context.set(CONTEXT, f.get("context", "ask"))
        self.links.set(LINKS, f.get("links", "ask"))
        size = str(f.get("max_mb", 500))
        self.sizes.set(SIZES if size in dict(SIZES) else SIZES + [(size, f"{size} MB")], size)
        kvm = data.get("kvm") or {}
        self.kvm.set_active(bool(kvm.get("on")))
        self.kvm.set_sensitive(bool(kvm.get("installed")) and bool(peers) and bool(data.get("enabled")))
        self.kvm_sub.set_text(kvm_text(kvm))
        self.kvm_more.set_text(kvm_details(kvm))
        self.kvm_install.set_visible(not kvm.get("installed"))
        clear(self.sides)
        if kvm.get("installed"):
            for p in peers:
                chips = Chips(lambda key, pid=p["id"]: self.side(pid, key))
                chips.set(SIDES, p.get("kvm_side") or "")
                grid, _ = row("\uf245", f"{p['name']} is", "which side of this screen" + (
                              "" if p.get("kvm_fp") else "  ·  waits for it to turn this on too"), None)
                self.sides.pack_start(grid, False, False, 0)
                self.sides.pack_start(chips.widget, False, False, 0)
        self.widget.show_all()
        if not (self.asking and self.proc and self.proc.poll() is None):
            self.answer.hide()      # show_all() above: the buttons only while a code is shown
        self.kvm_install.set_visible(not kvm.get("installed"))
        self.updating = False
