"""Settings page: Network & Bluetooth (network-settings.py).

Top to bottom: whether this computer is online and through what, its name on
the network, airplane mode; the wired link (its addresses, gateway, DNS and
traffic since boot in a fold); Wi-Fi -- the radio, the networks in range
(Connect asks for the password right in the list), a hidden network, the
saved networks with auto-connect and Forget; VPN connections (on / off,
import an .ovpn or WireGuard .conf, edit); and Bluetooth -- power, visible
to other devices, the paired devices with battery and connect / disconnect /
remove, and a scan to pair new ones.

Every control runs network-settings.py (the one place that knows how to do
each thing, also usable from the search bar or a terminal) in a thread and
then redraws from what NetworkManager and BlueZ report, so a switch never
shows a state the system is not in. The page re-reads every few seconds
while it is on screen (connections come up and devices connect on their own
time) but only rebuilds a section whose data actually changed, so a
password half typed is never wiped.

Anything that would cut the network (Disconnect on the wired link, Forget,
Remove) is a two-click button: the first click asks "Sure?", the second does
it, and it resets itself after a few seconds.
"""
import json
import subprocess
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import GLib, Gtk  # noqa: F401,E402

from .common import *  # noqa: F401,F403  (the shared helpers and paths)

PAGE = {"id": "network", "title": "Network & Bluetooth", "icon": "", "group": "Hardware", "order": 10,
        "keywords": ["internet", "wifi", "wireless", "ethernet", "wired", "ip address", "dns", "gateway",
                     "vpn", "wireguard", "openvpn", "bluetooth", "pair", "airplane mode", "flight mode",
                     "hostname", "computer name", "red"]}

NETSET = os.path.join(HYPR, "network-settings.py")  # noqa: F405
DEFAULT_APPS = os.path.join(HYPR, "default-apps.py")  # noqa: F405  (the terminal the user chose)
POLL_S = 4                       # re-read while the page is on screen
SCAN_POLL_MS = 1500              # faster while a Bluetooth scan is running

ICON_GLOBE, ICON_ETHERNET, ICON_WIFI, ICON_VPN = "", "", "", ""
ICON_PLANE, ICON_PC, ICON_BT, ICON_EYE, ICON_SEARCH = "", "", "", "", ""
# BlueZ's Icon property (freedesktop icon names) -> a Font Awesome glyph.
BT_ICONS = {"audio-headset": "", "audio-headphones": "", "audio-card": "",
            "input-mouse": "", "input-keyboard": "", "input-gaming": "",
            "input-tablet": "", "phone": "", "computer": "", "camera-video": "",
            "camera-photo": "", "printer": "", "multimedia-player": ""}
VPN_KINDS = {"openvpn": "OpenVPN", "openconnect": "OpenConnect (Cisco AnyConnect and friends)", "vpnc": "Cisco VPNC",
             "pptp": "PPTP", "l2tp": "L2TP", "fortisslvpn": "Fortinet SSL", "libreswan": "IPsec", "strongswan": "IPsec"}
CONNECTIVITY = {"full": ("Online", "internet reachable"),
                "limited": ("Connected, but no internet", "local network only"),
                "portal": ("A sign-in page is in the way", "open the sign-in page to get online"),
                "none": ("Offline", "no network connection"),
                "unknown": ("Connection state unknown", "not checked yet")}


def wifi_sub(net):
    """The subtitle of a network in the list: '▂▄▆_ 72%  ·  WPA2  ·  5 GHz  ·  saved'."""
    bits = [f"{net['bars']} {net['signal']}%", "open" if net["kind"] == "open" else net["security"]]
    if net.get("band"):
        bits.append(net["band"])
    if net["in_use"]:
        bits.insert(0, "connected")
    elif net["saved"]:
        bits.append("saved")
    if net["kind"] in ("enterprise", "wep"):
        bits.append("needs the connection editor")
    return "  ·  ".join(bits)


def bt_sub(dev):
    """'connected  ·  battery 80%' / 'paired, not connected' / 'signal -60 dBm'."""
    if dev["paired"]:
        bits = ["connected" if dev["connected"] else "paired, not connected"]
    else:
        bits = ["not paired"] + ([f"signal {dev['rssi']} dBm"] if dev.get("rssi") is not None else [])
    if dev.get("battery") is not None:
        bits.append(f"battery {dev['battery']}%")
    if dev.get("blocked"):
        bits.append("blocked")
    return "  ·  ".join(bits)


def when(stamp):
    if not stamp:
        return "never used"
    return "last used " + time.strftime("%d %b %Y", time.localtime(stamp))


class TwoClick:
    """A ctl-link that needs two clicks: the first turns it into "Sure? <text>",
    the second within a few seconds runs the action."""

    def __init__(self, text, action):
        self.text, self.action, self.armed = text, action, None
        self.widget = link(text, self.click)  # noqa: F405

    def click(self):
        if self.armed:
            GLib.source_remove(self.armed)
            self.armed = None
            self.widget.set_label(self.text)
            self.action()
            return
        self.widget.set_label(f"Sure? {self.text}")
        self.armed = GLib.timeout_add_seconds(4, self.disarm)

    def disarm(self):
        self.armed = None
        self.widget.set_label(self.text)
        return False


def switch(state, on_change):
    """A Gtk.Switch that never flips itself: on_change(wanted) runs the real
    command and the redraw sets the switch from what the system says."""
    sw = Gtk.Switch()
    sw.set_active(bool(state))
    sw.set_state(bool(state))
    sw.connect("state-set", lambda _s, wanted: (on_change(wanted), True)[1])
    return sw


def addr_grid(pairs):
    """A key / value grid (the network panel's sn-label / ns-value look);
    values are selectable so an address can be copied."""
    grid = Gtk.Grid()
    grid.set_column_spacing(14)
    grid.set_row_spacing(1)
    grid.set_margin_start(36)
    for i, (key, value) in enumerate(p for p in pairs if p[1]):
        k = dp.label(key, "sn-label")  # noqa: F405
        v = dp.label(value, "ns-value")  # noqa: F405
        v.set_selectable(True)
        v.set_can_focus(False)
        v.set_line_wrap(True)
        grid.attach(k, 0, i, 1, 1)
        grid.attach(v, 1, i, 1, 1)
    return grid


def keep_focus(entry):
    """Before a rebuild takes an entry out of its row: returns a function that,
    called after the entry is back in place, gives it the focus again if it
    had it -- WITHOUT selecting its text (a plain grab_focus() selects all,
    so the next key typed would replace a half-typed password)."""
    had = entry.has_focus()
    pos = entry.get_position()

    def restore():
        if had:
            entry.grab_focus_without_selecting()
            entry.set_position(pos)
    return restore


def note(text=""):
    lab = dp.label(text, "ctl-sub")  # noqa: F405
    lab.set_line_wrap(True)
    lab.set_no_show_all(not text)
    return lab


class Page:
    def __init__(self):
        self.widget = page_box()  # noqa: F405
        w = self.widget
        self.boxes, self.notes, self.seen = {}, {}, {}
        self.status, self.wifi_nets, self.bt = None, None, None
        self.busy = set()                          # sections with an action running
        self.prompt = None                         # SSID whose password row is open
        self.poll = self.scan_poll = None
        self.scan_until = 0
        self.traffic = {}                          # wired device -> its "since boot" label
        self.open_folds = {}                       # fold key -> expanded, kept across rebuilds

        # Kept across redraws so typing survives the poll.
        self.pw = Gtk.Entry()
        self.pw.set_visibility(False)
        self.pw.set_placeholder_text("password")
        self.pw.set_width_chars(24)
        self.pw.connect("activate", lambda _e: self.join(self.prompt))
        self.hidden_ssid, self.hidden_pw = Gtk.Entry(), Gtk.Entry()
        self.hidden_ssid.set_placeholder_text("network name")
        self.hidden_pw.set_placeholder_text("password (empty if open)")
        self.hidden_pw.set_visibility(False)
        self.hidden_pw.connect("activate", lambda _e: self.join_hidden())
        self.host = Gtk.Entry()
        self.host.set_width_chars(18)
        self.host.connect("activate", lambda _e: self.rename())

        self.link_rows = {}                         # section -> its row of links (Wi-Fi's hide with the radio)
        for key, title, links in (
                ("top", "CONNECTION", [link("Live traffic", lambda: spawn(PANEL, "toggle", "network"))]),  # noqa: F405
                ("wired", "WIRED", []),
                ("wifi", "WI-FI", [link("Rescan", lambda: self.load_wifi(True)),  # noqa: F405
                                   link("Hidden network…", self.toggle_hidden)]),  # noqa: F405
                ("saved", "SAVED WI-FI NETWORKS", []),
                ("vpn", "VPN", [link("Import a VPN file…", self.import_vpn),  # noqa: F405
                                link("Add another kind…", lambda: spawn("nm-connection-editor", "--create",  # noqa: F405
                                                                        "--type=vpn"))]),
                ("bt", "BLUETOOTH", []),
                ("btnew", "NEW BLUETOOTH DEVICES", [link("Look for devices", self.scan)])):  # noqa: F405
            if key != "top":
                w.pack_start(sep(), False, False, 0)  # noqa: F405
            w.pack_start(heading(title), False, False, 0)  # noqa: F405
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            w.pack_start(box, False, False, 0)
            self.boxes[key] = box
            if key == "wifi":
                self.hidden_row = Gtk.Box(spacing=8)
                for entry in (self.hidden_ssid, self.hidden_pw):
                    self.hidden_row.pack_start(entry, True, True, 0)
                self.hidden_row.pack_start(link("Join", self.join_hidden), False, False, 0)  # noqa: F405
                self.hidden_row.set_no_show_all(True)
                w.pack_start(self.hidden_row, False, False, 0)
            self.notes[key] = note()
            w.pack_start(self.notes[key], False, False, 0)
            if links:
                self.link_rows[key] = links_row(*links)  # noqa: F405
                w.pack_start(self.link_rows[key], False, False, 0)
            if key == "top":                       # the power tools, folded
                w.pack_start(details(links_row(  # noqa: F405
                    link("Advanced (nmtui)", lambda: spawn(DEFAULT_APPS, "run", "terminal", "--", "nmtui")),  # noqa: F405
                    link("Connection editor", lambda: spawn("nm-connection-editor"))),  # noqa: F405
                    label="Advanced"), False, False, 0)
        tip = note("Put the device in pairing mode, then Look for devices and Pair.")
        tip.set_no_show_all(False)
        w.pack_start(tip, False, False, 0)
        for key in self.boxes:
            self.boxes[key].pack_start(dp.label("checking…", "ctl-sub"), False, False, 0)  # noqa: F405

    # -- reading ---------------------------------------------------------------------
    def refresh(self):
        self.load()
        if self.poll is None:
            self.poll = GLib.timeout_add_seconds(POLL_S, self.tick)

    def tick(self):
        if not self.widget.get_mapped():           # page hidden or window closed: stop until shown again
            self.poll = None
            return False
        self.load()
        return True

    def load(self):
        background(lambda: run_json(NETSET, "status"), self.show_status)  # noqa: F405
        self.load_bt()
        self.load_wifi(False)

    def load_wifi(self, rescan):
        if rescan:
            self.say("wifi", "looking for networks…")
        background(lambda: run_json(NETSET, "wifi-list", *(["--rescan"] if rescan else []), timeout=40),  # noqa: F405
                   lambda nets: (self.show_wifi_list(nets), rescan and self.say("wifi", "")))

    def load_bt(self):
        background(lambda: run_json(NETSET, "bt", "status"), self.show_bt)  # noqa: F405

    def changed(self, key, data):
        """True (and remembered) when a section's data differs from what is drawn."""
        blob = json.dumps(data, sort_keys=True, default=str)
        if self.seen.get(key) == blob:
            return False
        self.seen[key] = blob
        return True

    def say(self, key, text, error=False):
        lab = self.notes[key]
        lab.set_text(text)
        style = lab.get_style_context()
        (style.add_class if error else style.remove_class)("error")
        lab.set_no_show_all(not text)
        lab.set_visible(bool(text))

    def act(self, key, busy_text, *args, stdin=None, then=None):
        """network-settings.py <args> in a thread; its line goes under the
        section, then everything is re-read."""
        self.say(key, busy_text)
        self.busy.add(key)

        def work():
            try:
                p = subprocess.run([NETSET, *args], capture_output=True, text=True, timeout=200, input=stdin)
                return p.returncode == 0, (p.stdout.strip() or p.stderr.strip()).splitlines()[-1:] or [""]
            except (OSError, subprocess.SubprocessError) as exc:
                return False, [str(exc)]

        def finished(result):
            ok, lines = result
            self.busy.discard(key)
            self.say(key, lines[0], error=not ok)
            self.seen.clear()                      # redraw everything from the new state
            if then:
                then(ok)
            self.load()
        background(work, finished)  # noqa: F405

    # -- top: online, name, airplane -------------------------------------------------
    def show_status(self, st):
        if not st:
            clear(self.boxes["top"])  # noqa: F405
            self.boxes["top"].pack_start(dp.label("network-settings.py did not answer", "ctl-sub"),  # noqa: F405
                                         False, False, 0)
            self.boxes["top"].show_all()
            return
        self.status = st
        self.show_top(st)
        self.show_wired(st)
        self.show_wifi_head(st)
        self.show_saved(st)
        self.show_vpn(st)
        if self.bt is not None:                    # its subtitle mentions airplane mode
            self.show_bt(self.bt)

    def show_top(self, st):
        if not self.changed("top", {k: st[k] for k in ("hostname", "connectivity", "default_iface", "airplane",
                                                         "networking")} | {"c": self.active_names(st)}):
            return
        box = self.boxes["top"]
        clear(box)  # noqa: F405
        title, sub = CONNECTIVITY.get(st["connectivity"], CONNECTIVITY["unknown"])
        via = self.active_names(st)
        if not st["networking"]:
            title, sub = "Networking is off", "all networking is disabled"
        elif via:
            sub += "  ·  via " + ", ".join(via)
        grid, _ = row(ICON_GLOBE, title, sub,  # noqa: F405
                      link("Open the sign-in page", lambda: spawn("xdg-open", "http://neverssl.com"))  # noqa: F405
                      if st["connectivity"] == "portal" else None)
        if st["connectivity"] == "full":
            grid.get_style_context().add_class("on")
        box.pack_start(grid, False, False, 0)

        if not self.host.has_focus():
            self.host.set_text(st["hostname"])
        refocus = keep_focus(self.host)
        if self.host.get_parent():                 # the entry is kept; only its row is rebuilt
            self.host.get_parent().remove(self.host)
        name = Gtk.Box(spacing=6)
        name.pack_start(self.host, False, False, 0)
        name.pack_start(link("Rename", self.rename), False, False, 0)  # noqa: F405
        grid, _ = row(ICON_PC, "This computer's name", "how other devices see it", name)  # noqa: F405
        box.pack_start(grid, False, False, 0)

        grid, _ = row(ICON_PLANE, "Airplane mode", "Wi-Fi and Bluetooth off  ·  the cable still works"  # noqa: F405
                      if st["airplane"] else "turns Wi-Fi and Bluetooth off",
                      switch(st["airplane"], lambda on: self.act("top", "airplane mode…", "airplane",
                                                                 "on" if on else "off")))
        if st["airplane"]:
            grid.get_style_context().add_class("on")
        box.pack_start(grid, False, False, 0)
        box.show_all()
        refocus()

    @staticmethod
    def active_names(st):
        out = []
        for c in st["connections"]:
            if c["active"] and c["type"] not in ("loopback",):
                kind = {"802-3-ethernet": "cable", "802-11-wireless": "Wi-Fi"}.get(c["type"], "VPN")
                out.append(f"{c['name']} ({kind})")
        return out

    def rename(self):
        new = self.host.get_text().strip()
        if self.status and new == self.status.get("hostname"):
            self.say("top", "that is already its name")
            return
        self.act("top", "renaming… (asks for your password)", "hostname", new)

    # -- wired -----------------------------------------------------------------------
    def show_wired(self, st):
        devs = [d for d in st["devices"] if d["type"] == "ethernet"]
        if not self.changed("wired", [{k: v for k, v in d.items() if k not in ("rx", "tx")} for d in devs]):
            self.update_traffic(devs)
            return
        box = self.boxes["wired"]
        clear(box)  # noqa: F405
        self.traffic = {}
        if not devs:
            box.pack_start(dp.label("No network port found.", "ctl-sub"), False, False, 0)  # noqa: F405
        for d in devs:
            up = d["state"] == "connected"
            uuid = next((c["uuid"] for c in st["connections"] if c["device"] == d["name"] and c["active"]), None)
            if up and uuid:
                button = TwoClick("Disconnect", lambda u=uuid: self.act(
                    "wired", "disconnecting…", "down", u)).widget
            elif d["state"] == "unavailable":
                button = None
            else:
                button = link("Connect", lambda n=d["name"]: self.act(  # noqa: F405
                    "wired", "connecting…", "device-connect", n))
            sub = "  ·  ".join(x for x in (d["speed"], "cable unplugged" if d["state"] == "unavailable"
                                           else d["state"]) if x)
            grid, _ = row(ICON_ETHERNET, d["connection"] or "Wired", sub, button)  # noqa: F405
            if up:
                grid.get_style_context().add_class("on")
            box.pack_start(grid, False, False, 0)
            if up:
                grid = addr_grid(self.addr_pairs(d))
                box.pack_start(self.fold("wired-" + d["name"], grid, "Addresses"), False, False, 0)
                self.traffic[d["name"]] = next((c for c in grid.get_children()
                                                if c.get_text().startswith("↓")), None)
        box.show_all()

    @staticmethod
    def addr_pairs(d):
        return [("IPv4", "\n".join(d["ipv4"]) or "none"), ("IPv6", "\n".join(d["ipv6"]) or "none"),
                ("Gateway", "  ·  ".join(g for g in (d["gateway"], d["gateway6"]) if g)),
                ("DNS", "  ·  ".join(d["dns"])), ("MAC", d["mac"]),
                ("Since boot", f"↓ {d['rx']}   ↑ {d['tx']}" if d.get("rx") else "")]

    def fold(self, key, widget, label):
        """A details() fold that stays open across the section's rebuilds."""
        fold = details(widget, label=label)  # noqa: F405
        fold.set_expanded(self.open_folds.get(key, False))
        fold.connect("notify::expanded", lambda f, _p: self.open_folds.__setitem__(key, f.get_expanded()))
        return fold

    def update_traffic(self, devs):
        """Only the byte counters moved: patch that one value in place."""
        for d in devs:
            lab = self.traffic.get(d["name"])
            if lab is not None and d.get("rx"):
                lab.set_text(f"↓ {d['rx']}   ↑ {d['tx']}")

    # -- Wi-Fi -----------------------------------------------------------------------
    def wifi_dev(self):
        st = self.status or {}
        return next((d for d in st.get("devices", []) if d["type"] == "wifi"), None)

    def show_wifi_head(self, st):
        self.redraw_wifi()

    def show_wifi_list(self, nets):
        self.wifi_nets = nets if isinstance(nets, list) else []
        self.redraw_wifi()

    def redraw_wifi(self):
        st = self.status
        if st is None:
            return
        dev = self.wifi_dev()
        data = {"radio": st["wifi"], "dev": {k: v for k, v in (dev or {}).items() if k not in ("rx", "tx")},
                "nets": self.wifi_nets, "prompt": self.prompt, "airplane": st["airplane"]}
        if not self.changed("wifi", data):
            return
        box = self.boxes["wifi"]
        # Rescan and Hidden network… only mean something with the radio on:
        # hidden (with the hidden-network fields) while Wi-Fi is off.
        radio = bool(st["wifi"]["device"] and st["wifi"]["radio"] and dev and dev["state"] != "unavailable")
        wifi_links = self.link_rows["wifi"]
        wifi_links.set_no_show_all(not radio)
        wifi_links.show_all() if radio else wifi_links.hide()
        if not radio:
            self.hidden_row.hide()
            self.hidden_row.set_no_show_all(True)
        refocus = keep_focus(self.pw)
        if self.pw.get_parent():
            self.pw.get_parent().remove(self.pw)
        clear(box)  # noqa: F405
        if not st["wifi"]["device"]:
            box.pack_start(dp.label("No Wi-Fi adapter.", "ctl-sub"), False, False, 0)  # noqa: F405
            box.show_all()
            return
        current = next((n for n in self.wifi_nets or [] if n["in_use"]), None)
        if not st["wifi"]["radio"]:
            sub = "off" + ("  ·  airplane mode is on" if st["airplane"] else "")
        elif dev and dev["state"] == "connected":
            sub = f"connected to {dev['connection']}" + (f"  ·  {current['bars']} {current['signal']}%  ·  "
                                                          f"{current['rate']}" if current else "")
        else:
            sub = f"on  ·  {dev['state'] if dev else '?'}"
        grid, _ = row(ICON_WIFI, "Wi-Fi", sub, switch(st["wifi"]["radio"], lambda on: self.act(  # noqa: F405
            "wifi", "turning Wi-Fi " + ("on…" if on else "off…"), "wifi", "on" if on else "off")))
        if st["wifi"]["radio"]:
            grid.get_style_context().add_class("on")
        box.pack_start(grid, False, False, 0)
        if dev and dev["state"] == "connected":
            box.pack_start(self.fold("wifi", addr_grid(self.addr_pairs(dev)), "Addresses"), False, False, 0)
        if not radio:
            box.show_all()
            return
        if self.wifi_nets is None:
            box.pack_start(dp.label("looking for networks…", "ctl-sub"), False, False, 0)  # noqa: F405
        elif not self.wifi_nets:
            box.pack_start(dp.label("No networks in range.", "ctl-sub"), False, False, 0)  # noqa: F405
        for net in (self.wifi_nets or [])[:20]:
            if net["in_use"]:
                uuid = next((c["uuid"] for c in st["connections"] if c["active"] and c.get("ssid") == net["ssid"]),
                            net["saved"])
                button = TwoClick("Disconnect", lambda u=uuid: self.act("wifi", "disconnecting…", "down", u)).widget
            elif net["kind"] in ("enterprise", "wep"):
                button = link("Set up…", lambda: spawn("nm-connection-editor", "--create",  # noqa: F405
                                                       "--type=802-11-wireless"))
            else:
                button = link("Connect", lambda n=net: self.connect_net(n))  # noqa: F405
            grid, _ = row(ICON_WIFI, net["ssid"], wifi_sub(net), button)  # noqa: F405
            if net["in_use"]:
                grid.get_style_context().add_class("on")
            box.pack_start(grid, False, False, 0)
            if self.prompt == net["ssid"]:
                line = Gtk.Box(spacing=8)
                line.set_margin_start(36)
                line.pack_start(self.pw, True, True, 0)
                show = Gtk.CheckButton(label="show")
                show.set_active(self.pw.get_visibility())
                show.connect("toggled", lambda b: self.pw.set_visibility(b.get_active()))
                line.pack_start(show, False, False, 0)
                line.pack_start(link("Join", lambda: self.join(self.prompt)), False, False, 0)  # noqa: F405
                line.pack_start(link("Cancel", self.cancel_prompt), False, False, 0)  # noqa: F405
                box.pack_start(line, False, False, 0)
        box.show_all()
        refocus()                                  # the list redraws as signals move: keep the typing

    def connect_net(self, net):
        if net["saved"]:
            self.act("wifi", f"connecting to {net['ssid']}…", "up", net["saved"],
                     then=lambda ok: ok or self.ask_password(net["ssid"]))
        elif net["kind"] in ("open", "owe"):
            self.act("wifi", f"joining {net['ssid']}…", "wifi-connect", net["ssid"])
        else:
            self.ask_password(net["ssid"])

    def ask_password(self, ssid):
        self.prompt = ssid
        self.pw.set_text("")
        self.redraw_wifi()
        if self.pw.get_parent():
            self.pw.grab_focus_without_selecting()
        return True

    def cancel_prompt(self):
        self.prompt = None
        self.pw.set_text("")
        self.redraw_wifi()

    def join(self, ssid):
        if not ssid:
            return
        password = self.pw.get_text()
        if len(password) < 8:
            self.say("wifi", "Wi-Fi passwords are at least 8 characters", error=True)
            return
        self.prompt = None
        self.pw.set_text("")
        self.act("wifi", f"joining {ssid}… (up to 45 s)", "wifi-connect", ssid, "--password-stdin",
                 stdin=password + "\n")

    def toggle_hidden(self):
        show = not self.hidden_row.get_visible()
        self.hidden_row.set_no_show_all(not show)
        self.hidden_row.show_all() if show else self.hidden_row.hide()
        if show:
            self.hidden_ssid.grab_focus()

    def join_hidden(self):
        ssid, password = self.hidden_ssid.get_text().strip(), self.hidden_pw.get_text()
        if not ssid:
            self.say("wifi", "type the network's name first", error=True)
            return
        self.hidden_pw.set_text("")
        self.toggle_hidden()
        self.act("wifi", f"joining {ssid}… (up to 45 s)", "wifi-connect", ssid, "--hidden",
                 *(["--password-stdin"] if password else []), stdin=(password + "\n") if password else None)

    def show_saved(self, st):
        saved = [c for c in st["connections"] if c["type"] == "802-11-wireless"]
        if not self.changed("saved", saved):
            return
        box = self.boxes["saved"]
        clear(box)  # noqa: F405
        if not saved:
            box.pack_start(dp.label("None yet.", "ctl-sub"), False, False, 0)  # noqa: F405
        for c in saved:
            end = Gtk.Box(spacing=8)
            end.pack_start(dp.label("auto-connect", "ctl-sub"), False, False, 0)  # noqa: F405
            end.pack_start(switch(c["autoconnect"], lambda on, u=c["uuid"]: self.act(
                "saved", "saving…", "autoconnect", u, "on" if on else "off")), False, False, 0)
            end.pack_start(TwoClick("Forget", lambda u=c["uuid"]: self.act(
                "saved", "forgetting…", "forget", u)).widget, False, False, 0)
            sub = "  ·  ".join(x for x in ("connected" if c["active"] else "", when(c["last_used"]),
                                           "" if c.get("ssid") in (c["name"], None) else c["ssid"]) if x)
            grid, _ = row(ICON_WIFI, c["name"], sub, end)  # noqa: F405
            box.pack_start(grid, False, False, 0)
        box.show_all()

    # -- VPN -------------------------------------------------------------------------
    def show_vpn(self, st):
        vpns = [c for c in st["connections"] if c["type"] in ("vpn", "wireguard")]
        if not self.changed("vpn", vpns):
            return
        box = self.boxes["vpn"]
        clear(box)  # noqa: F405
        if not vpns:
            lab = dp.label("No VPN yet: import your provider's .ovpn or WireGuard .conf.", "ctl-sub")  # noqa: F405
            lab.set_line_wrap(True)
            box.pack_start(lab, False, False, 0)
        for c in vpns:
            end = Gtk.Box(spacing=8)
            end.pack_start(link("Edit…", lambda u=c["uuid"]: spawn("nm-connection-editor",  # noqa: F405
                                                                   f"--edit={u}")), False, False, 0)
            end.pack_start(TwoClick("Remove", lambda u=c["uuid"]: self.act(
                "vpn", "removing…", "forget", u)).widget, False, False, 0)
            end.pack_start(switch(c["active"], lambda on, u=c["uuid"], n=c["name"]: self.act(
                "vpn", (f"connecting {n}…" if on else f"disconnecting {n}…"), "up" if on else "down", u)),
                False, False, 0)
            kind = "WireGuard" if c["type"] == "wireguard" else VPN_KINDS.get(c.get("vpn_kind"), (
                c.get("vpn_kind") or "VPN").capitalize())
            state = "connecting…" if c["state"] == "activating" else "connected" if c["active"] else "off"
            grid, _ = row(ICON_VPN, c["name"], f"{kind}  ·  {state}  ·  auto-connect "  # noqa: F405
                          f"{'on' if c['autoconnect'] else 'off'}", end)
            if c["active"]:
                grid.get_style_context().add_class("on")
            box.pack_start(grid, False, False, 0)
        box.show_all()

    def import_vpn(self):
        dialog = Gtk.FileChooserDialog(title="Import a VPN file", transient_for=self.widget.get_toplevel()
                                       if isinstance(self.widget.get_toplevel(), Gtk.Window) else None,
                                       action=Gtk.FileChooserAction.OPEN)
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Import", Gtk.ResponseType.OK)
        filt = Gtk.FileFilter()
        filt.set_name("VPN files (.ovpn, .conf)")
        for pattern in ("*.ovpn", "*.conf", "*.OVPN", "*.CONF"):
            filt.add_pattern(pattern)
        dialog.add_filter(filt)
        dialog.set_current_folder(os.path.expanduser("~/Downloads"))  # noqa: F405
        path = dialog.get_filename() if dialog.run() == Gtk.ResponseType.OK else None
        dialog.destroy()
        if path:
            self.act("vpn", "importing…", "vpn-import", path)

    # -- Bluetooth -------------------------------------------------------------------
    def show_bt(self, bt):
        self.bt = bt or {"present": False, "service": False, "devices": []}
        bt = self.bt
        scanning = bt.get("discovering") or time.monotonic() < self.scan_until
        if scanning and not self.scan_poll:
            self.scan_poll = GLib.timeout_add(SCAN_POLL_MS, self.scan_tick)
        if self.changed("bt", {k: v for k, v in bt.items() if k != "devices"}
                        | {"paired": [d for d in bt.get("devices", []) if d["paired"]],
                           "airplane": (self.status or {}).get("airplane")}):
            self.draw_bt(bt)
        found = [{k: v for k, v in d.items() if k != "rssi"} for d in bt.get("devices", []) if not d["paired"]]
        if self.changed("btnew", {"found": found, "scan": scanning, "on": bt.get("powered")}):
            self.draw_btnew(bt, scanning)

    def scan_tick(self):
        if time.monotonic() > self.scan_until + 2 or not self.widget.get_mapped():
            self.scan_poll = None
            self.load_bt()
            return False
        self.load_bt()
        return True

    def draw_bt(self, bt):
        box = self.boxes["bt"]
        clear(box)  # noqa: F405
        if not bt.get("service"):
            box.pack_start(dp.label("The Bluetooth service is not running.", "ctl-sub"), False, False, 0)  # noqa: F405
        elif not bt.get("present"):
            box.pack_start(dp.label("No Bluetooth adapter found.", "ctl-sub"), False, False, 0)  # noqa: F405
        else:
            if bt.get("hard_blocked"):
                sub = "blocked by a hardware switch or the BIOS"
            elif bt["powered"]:
                sub = f"on  ·  shows up as “{bt['name']}”"
            else:
                sub = "off" + ("  ·  airplane mode is on" if (self.status or {}).get("airplane") else "")
            grid, _ = row(ICON_BT, "Bluetooth", sub, switch(bt["powered"], lambda on: self.act(  # noqa: F405
                "bt", "turning Bluetooth " + ("on…" if on else "off…"), "bt", "power", "on" if on else "off")))
            if bt["powered"]:
                grid.get_style_context().add_class("on")
            box.pack_start(grid, False, False, 0)
            if bt["powered"]:
                minutes = round((bt.get("discoverable_timeout") or 0) / 60)
                grid, _ = row(ICON_EYE, "Visible to other devices",  # noqa: F405
                              "lets phones and computers find it" +
                              (f"  ·  off after {minutes} min" if minutes else ""),
                              switch(bt["discoverable"], lambda on: self.act(
                                  "bt", "making it visible…" if on else "hiding it…", "bt", "discoverable",
                                  "on" if on else "off")))
                if bt["discoverable"]:
                    grid.get_style_context().add_class("on")
                box.pack_start(grid, False, False, 0)
            paired = [d for d in bt["devices"] if d["paired"]]
            box.pack_start(dp.label(f"Paired devices ({len(paired)})" if paired else "No paired devices yet.",  # noqa: F405
                                    "ctl-sub"), False, False, 0)
            for d in paired:
                end = Gtk.Box(spacing=8)
                if bt["powered"]:
                    verb = "disconnect" if d["connected"] else "connect"
                    end.pack_start(link(verb.capitalize(), lambda m=d["mac"], v=verb, n=d["name"]: self.act(  # noqa: F405
                        "bt", f"{v}ing {n}…", "bt", v, m)), False, False, 0)
                end.pack_start(TwoClick("Remove", lambda m=d["mac"]: self.act(
                    "bt", "removing…", "bt", "remove", m)).widget, False, False, 0)
                grid, _ = row(BT_ICONS.get(d["icon"], ICON_BT), d["name"], bt_sub(d), end)  # noqa: F405
                if d["connected"]:
                    grid.get_style_context().add_class("on")
                box.pack_start(grid, False, False, 0)
        box.show_all()

    def draw_btnew(self, bt, scanning):
        box = self.boxes["btnew"]
        clear(box)  # noqa: F405
        # Like Wi-Fi's Rescan: "Look for devices" only while Bluetooth is on.
        on = bool(bt.get("present") and bt.get("powered"))
        bt_links = self.link_rows["btnew"]
        bt_links.set_no_show_all(not on)
        bt_links.show_all() if on else bt_links.hide()
        found = [d for d in bt.get("devices", []) if not d["paired"]]
        if not bt.get("present"):
            pass
        elif not bt.get("powered"):
            box.pack_start(dp.label("Turn Bluetooth on to look for devices.", "ctl-sub"), False, False, 0)  # noqa: F405
        elif scanning:
            box.pack_start(dp.label(f"looking…  ·  {len(found)} found so far", "ctl-sub"), False, False, 0)  # noqa: F405
        elif not found:
            box.pack_start(dp.label("Nothing found yet.", "ctl-sub"), False, False, 0)  # noqa: F405
        for d in found[:15]:
            grid, _ = row(BT_ICONS.get(d["icon"], ICON_BT), d["name"], bt_sub(d),  # noqa: F405
                          link("Pair", lambda m=d["mac"], n=d["name"]: self.act(  # noqa: F405
                              "btnew", f"pairing with {n}… (up to 40 s)", "bt", "pair", m)))
            box.pack_start(grid, False, False, 0)
        box.show_all()

    def scan(self):
        if not (self.bt or {}).get("powered"):
            self.say("btnew", "turn Bluetooth on first", error=True)
            return
        self.scan_until = time.monotonic() + 12
        self.seen.pop("btnew", None)
        self.act("btnew", "looking for devices for 12 s…", "bt", "scan", "12")
        self.load_bt()
