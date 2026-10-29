#!/usr/bin/env python3
"""Network panel — what the network pill opens.

A switch for the Wi-Fi radio, then one switch per saved NetworkManager
connection: on brings it up, off takes it down. Saved connections only —
joining a network you have never used needs a password prompt, and that is
what "Advanced" (nmtui, the pill's old left-click) is still for.

Everything is nmcli, run in a thread: bringing a connection up can take several
seconds (DHCP, Wi-Fi association), and doing that on the GTK thread would
freeze the panel. While it runs the row says so and its switch is locked; when
it finishes the row is redrawn from NetworkManager's own state, not from what
the switch was asked to do, so a failure can never leave a switch showing "on"
for a connection that is down. nmcli's error, if any, replaces the row's
subtitle.

Turning the wired connection off does exactly that — this machine goes offline
until you turn it back on. No confirmation, because the switch is right there
to undo it.

VPN and WireGuard profiles are a section of their own under the rest
(VPN_TYPES, network.py's list: the same ones that put a shield on the pill),
with the same on / off switch -- hidden while there are none saved.

Rows are keyed on the connection UUID, never the name: names here include
emoji and brackets, and nothing stops two profiles sharing one.

Above the switches: live stats for the interface carrying the default route
-- download/upload rate with a small graph of each, then addresses, gateway,
DNS and link speed. These used to be the network pill's hover tooltip, which
popped up over this panel and the audio sliders next to it; the pill's
tooltip is off now. The data comes from network.py (the pill's own script),
so the two can never disagree about what they measure. Rates sample every
second while the panel is open; the graphs cover the last minute.

Two columns: the stats and the switches on the left, and on the right APPS
ONLINE: which of your apps have connections open and
how fast each is moving data, from netprocs.py (per-socket TCP byte counters,
sampled every two seconds). UDP has no such counters, so QUIC in browsers,
qBittorrent's uTP and game traffic count as connections but under-read in the
rates -- the panel says so under the table. Each app has the shared
two-click End button (proctable.py).

    network_panel.py [x,y]   desktop position of the click that opened it
"""

import os
import re
import subprocess
import sys
import threading

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import netprocs  # noqa: E402
import panelui  # noqa: E402
from proctable import ProcTable  # noqa: E402
import network as netinfo  # noqa: E402  -- the pill's script, for its helpers
from sensors_panel import Graph  # noqa: E402
import themecolors  # noqa: E402

RATE_MS = 1000
RATE_POINTS = 60            # one minute of 1s samples
INFO_EVERY = 5              # re-read addresses/DNS every Nth rate tick
# Download / upload graphs: the theme's color.net_down / color.net_up
# (themecolors.py), cyberpunk's cyan and magenta as the fallback.
CYAN = themecolors.rgb("net_down", "#00f0ff")
MAGENTA = themecolors.rgb("net_up", "#ff2a6d")

POLL_MS = 2000
TIMEOUT = 45                # nmcli's own default wait is 90s; give up sooner

ICON_WIFI = "\uf1eb"
ICON_ETHERNET = "\uf796"
ICON_VPN = "\uf023"
ICON_OTHER = "\uf0c1"

TYPE_ICONS = {"802-11-wireless": ICON_WIFI, "802-3-ethernet": ICON_ETHERNET,
              "vpn": ICON_VPN, "wireguard": ICON_VPN}
HIDDEN_TYPES = {"loopback", "bridge", "tun"}
VPN_TYPES = set(netinfo.VPN_TYPES)


def split_vpns(conns):
    """(the other connections, the VPN / WireGuard ones), each in the order
    given: the VPN section lists its own below the rest."""
    return ([c for c in conns if c["type"] not in VPN_TYPES],
            [c for c in conns if c["type"] in VPN_TYPES])


def nmcli(*args, timeout=5):
    """(ok, stdout, first line of stderr)."""
    try:
        proc = subprocess.run(["nmcli", *args], capture_output=True, text=True,
                              timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "", "timed out"
    except OSError as exc:
        return False, "", str(exc)
    err = proc.stderr.strip().splitlines()
    return proc.returncode == 0, proc.stdout, (err[-1] if err else "")


def split_terse(line):
    """nmcli -t separates fields with ':' and escapes literal ones as '\\:'."""
    return [f.replace("\\:", ":").replace("\\\\", "\\")
            for f in re.split(r"(?<!\\):", line)]


def read_state():
    ok, out, _ = nmcli("-t", "radio", "wifi")
    wifi_on = out.strip() == "enabled"
    ok, out, _ = nmcli("-t", "-f", "NAME,UUID,TYPE,DEVICE,ACTIVE,STATE",
                       "connection", "show")
    conns = []
    for line in out.splitlines():
        fields = split_terse(line)
        if len(fields) < 6:
            continue
        name, uuid, ctype, device, active, state = fields[:6]
        if ctype in HIDDEN_TYPES:
            continue
        conns.append({"name": name, "uuid": uuid, "type": ctype, "device": device,
                      "active": active == "yes", "state": state})
    # Ethernet first, then whatever is up, then the rest by name.
    conns.sort(key=lambda c: (c["type"] != "802-3-ethernet", not c["active"],
                              c["name"].lower()))
    return wifi_on, conns


class SwitchRow:
    """Icon, title, subtitle, switch -- on ONE line (class "compact"), the
    subtitle dimmed and right-aligned after the title, so five connections fit
    in a card as tall as the CPU and GPU ones. The switch never changes
    itself: its state-set handler starts the action and returns True, and the
    row is only redrawn from NetworkManager afterwards."""

    def __init__(self, icon, on_toggle):
        self.on_toggle = on_toggle
        self.busy = False
        self.error = ""

        self.widget = Gtk.Grid()
        self.widget.get_style_context().add_class("ctl-row")
        self.widget.get_style_context().add_class("compact")
        self.widget.set_column_spacing(10)

        self.icon = Gtk.Label(label=icon)
        self.icon.get_style_context().add_class("ctl-icon")
        self.icon.set_valign(Gtk.Align.CENTER)
        self.widget.attach(self.icon, 0, 0, 1, 1)

        self.title = Gtk.Label(label="")
        self.title.get_style_context().add_class("ctl-title")
        self.title.set_xalign(0)
        self.title.set_ellipsize(3)
        self.title.set_width_chars(10)
        self.title.set_max_width_chars(20)
        self.widget.attach(self.title, 1, 0, 1, 1)

        self.sub = Gtk.Label(label="")
        self.sub.get_style_context().add_class("ctl-sub")
        self.sub.set_xalign(1)
        self.sub.set_hexpand(True)
        self.sub.set_ellipsize(3)
        self.sub.set_max_width_chars(22)
        self.widget.attach(self.sub, 2, 0, 1, 1)

        self.switch = Gtk.Switch()
        self.switch.set_valign(Gtk.Align.CENTER)
        self.switch.connect("state-set", self.on_state_set)
        self.widget.attach(self.switch, 3, 0, 1, 1)

    def set(self, title, sub, on, sensitive=True):
        self.title.set_text(title)
        style = self.widget.get_style_context()
        if self.busy:
            return
        if self.error:
            self.sub.set_text(self.error)
            style.add_class("error")
        else:
            self.sub.set_text(sub)
            style.remove_class("error")
        # One line is narrow; the full text is a hover away.
        self.sub.set_tooltip_text(self.sub.get_text())
        (style.add_class if on else style.remove_class)("on")
        self.switch.handler_block_by_func(self.on_state_set)
        self.switch.set_active(on)
        self.switch.set_state(on)
        self.switch.handler_unblock_by_func(self.on_state_set)
        self.switch.set_sensitive(sensitive)

    def on_state_set(self, _switch, wanted):
        if self.busy:
            return True
        self.busy = True
        self.error = ""
        self.switch.set_sensitive(False)
        self.widget.get_style_context().remove_class("error")
        self.sub.set_text("Connecting…" if wanted else "Disconnecting…")
        self.on_toggle(wanted)
        return True


class Stats:
    """Rates with sparklines, then a key/value block. Text only, no controls."""

    def __init__(self):
        self.widget = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.widget.get_style_context().add_class("ns-stats")

        self.title = Gtk.Label(label="")
        self.title.get_style_context().add_class("ctl-sub")
        self.title.set_xalign(0)
        self.widget.pack_start(self.title, False, False, 0)

        rates = Gtk.Grid()
        rates.set_column_spacing(10)
        rates.set_row_spacing(3)
        self.down_val, self.up_val = Gtk.Label(), Gtk.Label()
        self.down_graph = Graph(CYAN, 0, None, capacity=RATE_POINTS)
        self.up_graph = Graph(MAGENTA, 0, None, capacity=RATE_POINTS)
        for row, (arrow, graph, value) in enumerate(
                (("↓", self.down_graph, self.down_val),
                 ("↑", self.up_graph, self.up_val))):
            label = Gtk.Label(label=arrow)
            label.get_style_context().add_class("sn-label")
            rates.attach(label, 0, row, 1, 1)
            graph.set_size_request(200, 22)
            rates.attach(graph, 1, row, 1, 1)
            value.get_style_context().add_class("sn-value")
            value.set_xalign(1)
            value.set_width_chars(10)
            rates.attach(value, 2, row, 1, 1)
        self.widget.pack_start(rates, False, False, 4)

        self.info = Gtk.Grid()
        self.info.set_column_spacing(12)
        self.info.set_row_spacing(1)
        self.widget.pack_start(self.info, False, False, 0)

        self.prev, self.when = None, None
        self.down, self.up = [], []
        self.ticks = 0
        self.iface = None

    def tick(self):
        iface, gateway = netinfo.default_iface()
        cur = netinfo.counters(iface) if iface else None
        now = GLib.get_monotonic_time() / 1e6
        if iface != self.iface:                 # route moved: start over
            self.prev, self.down, self.up = None, [], []
            self.ticks = 0
            self.iface = iface
        if cur and self.prev:
            dt = max(now - self.when, 1e-3)
            self.down.append(max(cur["rx_bytes"] - self.prev["rx_bytes"], 0) / dt)
            self.up.append(max(cur["tx_bytes"] - self.prev["tx_bytes"], 0) / dt)
            self.down, self.up = self.down[-RATE_POINTS:], self.up[-RATE_POINTS:]
        self.prev, self.when = cur, now

        self.down_graph.set_values(self.down)
        self.up_graph.set_values(self.up)
        self.down_val.set_text(netinfo.human_rate(self.down[-1]) if self.down else "–")
        self.up_val.set_text(netinfo.human_rate(self.up[-1]) if self.up else "–")

        if self.ticks % INFO_EVERY == 0:
            self.fill_info(iface, gateway)
        self.ticks += 1

    def fill_info(self, iface, gateway):
        for child in self.info.get_children():
            child.destroy()
        if not iface:
            self.title.set_text("Offline — no default route")
            return
        link = netinfo.link_info(iface)
        wifi = netinfo.wifi_info(iface)
        v4, v6g, v6u, v6l = netinfo.addresses(iface)
        speed = link.get("speed", "")
        kind = "Wi-Fi" if wifi else "Ethernet"
        bits = [iface, kind]
        if speed and speed not in ("-1", "0"):
            bits.append(f"{speed} Mb/s")
        if wifi.get("ssid"):
            bits.append(wifi["ssid"])
        self.title.set_text("  ·  ".join(bits))

        if v6g:
            v6 = v6g[0]
        elif v6u:
            v6 = v6u[0] + " (ULA)"
        elif v6l:
            v6 = "link-local only"
        else:
            v6 = "none"
        rows = [("IPv4", v4[0] if v4 else "none"), ("IPv6", v6)]
        if gateway:
            rows.append(("GW", gateway))
        dns = netinfo.dns_for(iface)
        if dns:
            rows.append(("DNS", dns))
        if wifi.get("signal"):
            rows.append(("SIGNAL", wifi["signal"]))
        for row, (key, value) in enumerate(rows):
            k = Gtk.Label(label=key)
            k.get_style_context().add_class("sn-label")
            k.set_xalign(0)
            v = Gtk.Label(label=value)
            v.get_style_context().add_class("ns-value")
            v.set_xalign(0)
            v.set_ellipsize(3)
            v.set_max_width_chars(34)
            v.set_selectable(False)
            self.info.attach(k, 0, row, 1, 1)
            self.info.attach(v, 1, row, 1, 1)
        self.info.show_all()


class Network(panelui.Panel):
    def build(self):
        # Left: the link's graphs and details, then the switches.
        # Right: the apps using it.
        self.card.set_size_request(-1, panelui.CARD_HEIGHT)   # = CPU and GPU cards
        left, right = panelui.columns(self.card)

        # "Advanced" (nmtui) shares the heading's line, like htop / nvtop on
        # the CPU and GPU cards, instead of a row of its own at the bottom.
        top_line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        heading = Gtk.Label(label="NETWORK")
        heading.get_style_context().add_class("kb-heading")
        heading.set_xalign(0)
        top_line.pack_start(heading, True, True, 0)
        advanced = Gtk.Button(label="Advanced")
        advanced.get_style_context().add_class("ctl-link")
        advanced.get_style_context().add_class("sn-link")
        advanced.set_valign(Gtk.Align.START)
        advanced.connect("clicked", self.open_nmtui)
        top_line.pack_end(advanced, False, False, 0)
        left.pack_start(top_line, False, False, 0)

        self.stats = Stats()
        left.pack_start(self.stats.widget, False, False, 0)

        top = Gtk.Separator()
        top.get_style_context().add_class("ctl-sep")
        left.pack_start(top, False, False, 0)

        self.radio = SwitchRow(ICON_WIFI, self.toggle_radio)
        left.pack_start(self.radio.widget, False, False, 0)

        sep = Gtk.Separator()
        sep.get_style_context().add_class("ctl-sep")
        left.pack_start(sep, False, False, 0)

        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        left.pack_start(self.list, False, False, 0)
        self.rows = {}                       # uuid -> SwitchRow

        # VPN: hidden until a VPN / WireGuard profile is saved.
        self.vpn_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.vpn_box.set_no_show_all(True)
        vpn_head = Gtk.Label(label="VPN")
        vpn_head.get_style_context().add_class("kb-heading")
        vpn_head.set_xalign(0)
        vpn_head.set_margin_top(6)
        vpn_head.show()
        self.vpn_box.pack_start(vpn_head, False, False, 0)
        self.vpn_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.vpn_list.show()
        self.vpn_box.pack_start(self.vpn_list, False, False, 0)
        left.pack_start(self.vpn_box, False, False, 0)

        apps_head = Gtk.Label(label="APPS ONLINE")
        apps_head.get_style_context().add_class("kb-heading")
        apps_head.set_xalign(0)
        right.pack_start(apps_head, False, False, 0)
        self.sampler = netprocs.Sampler()
        self.apps = ProcTable(["conn", "down", "up"], on_ended=self.refresh_apps)
        right.pack_start(self.apps.widget, False, False, 0)
        udp = Gtk.Label(label="rates count TCP only -- QUIC, uTP and\ngame (UDP) traffic reads low")
        udp.get_style_context().add_class("ctl-sub")
        udp.set_xalign(0)
        udp.set_margin_top(6)
        right.pack_start(udp, False, False, 0)

        self.refresh()

    def on_ready(self):
        GLib.timeout_add(POLL_MS, self.poll)
        self.stats.tick()
        GLib.timeout_add(RATE_MS, self.rate_tick)

    def poll(self):
        self.refresh()
        self.refresh_apps()
        return True

    def refresh_apps(self):
        self.apps.set([{"name": a["name"], "pids": a["pids"],
                        "values": [str(a["conns"]), netprocs.rate(a["down"]), netprocs.rate(a["up"])]}
                       for a in self.sampler()])

    def rate_tick(self):
        self.stats.tick()
        return True

    # -- state --------------------------------------------------------------
    def refresh(self):
        wifi_on, conns = read_state()
        self.wifi_on = wifi_on
        self.radio.set("Wi-Fi", "Radio on" if wifi_on else "Radio off", wifi_on)

        seen = set()
        others, vpns = split_vpns(conns)
        for box, group in ((self.list, others), (self.vpn_list, vpns)):
            for index, conn in enumerate(group):
                seen.add(conn["uuid"])
                row = self.rows.get(conn["uuid"])
                if row is None:
                    row = SwitchRow(TYPE_ICONS.get(conn["type"], ICON_OTHER),
                                    lambda wanted, c=conn: self.toggle_conn(c, wanted))
                    self.rows[conn["uuid"]] = row
                    box.pack_start(row.widget, False, False, 0)
                    row.widget.show_all()
                box.reorder_child(row.widget, index)
                row.set(conn["name"], self.describe(conn), conn["active"],
                        sensitive=self.wifi_on or conn["type"] != "802-11-wireless")
        for uuid in list(self.rows):
            if uuid not in seen:
                self.rows.pop(uuid).widget.destroy()
        self.vpn_box.set_visible(bool(vpns))

    def describe(self, conn):
        if conn["state"] == "activating":
            return "Connecting…"
        if conn["active"]:
            return f"Connected · {conn['device']}" if conn["device"] else "Connected"
        if conn["type"] == "802-11-wireless" and not self.wifi_on:
            return "Wi-Fi is off"
        return "Not connected"

    # -- actions ------------------------------------------------------------
    def run(self, row, *args):
        def work():
            ok, _, err = nmcli(*args, timeout=TIMEOUT)
            GLib.idle_add(self.finished, row, ok, err)
        threading.Thread(target=work, daemon=True).start()

    def finished(self, row, ok, err):
        row.busy = False
        row.error = "" if ok else (err.removeprefix("Error: ") or "Failed")
        self.refresh()
        return False

    def toggle_radio(self, wanted):
        self.run(self.radio, "radio", "wifi", "on" if wanted else "off")

    def toggle_conn(self, conn, wanted):
        self.run(self.rows[conn["uuid"]], "connection", "up" if wanted else "down",
                 "uuid", conn["uuid"])

    def open_nmtui(self, _button):
        subprocess.Popen(["kitty", "-e", "nmtui"], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        self.quit()


def main():
    panelui.run(Network)


if __name__ == "__main__":
    main()
