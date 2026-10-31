#!/usr/bin/env python3
"""Network module for waybar, with a tooltip the built-in one cannot produce.

Why this replaces the built-in "network" module
-----------------------------------------------
waybar's own network module has no IPv6 format replacement at all. {ipaddr} is
IPv4 and only IPv4, so a tooltip built out of its placeholders can never show a
v6 address no matter how it is arranged. Everything else here -- live throughput,
DNS, link speed, error and drop counters -- is likewise unavailable to it.

The pill itself is deliberately unchanged: same text, same Font Awesome glyphs
(\uf1eb wifi, \uf0ac globe, \uf0c1 link) as the module this replaces, so the bar
looks identical and only hovering is different.

    network.py watch    JSON on stdout forever, for a module with no "interval"
    network.py once     one JSON line and exit, for testing (with the full
                        tooltip the module no longer shows)

The watcher is event-driven and builds the pill only. The module's tooltip
is off (the network panel has those stats, and the tooltip covered the audio
sliders), and the pill's text is the interface, its IPv4 address or the
Wi-Fi signal -- none of which is a rate. So `watch` no longer samples
throughput every 3 s or runs ip / resolvectl / iw for a tooltip nobody sees:
it sits on one `ip monitor link address route` and re-reads /proc/net/route
and the address (an ioctl, no fork) when that prints something, prints a
line only when the text changed, and re-checks on a timer only for the
Wi-Fi signal (WIFI_REFRESH; `iw`, Wi-Fi only) and as a safety net
(SAFETY_REFRESH). Without `ip` it falls back to a quiet POLL-second loop.
When the link comes up after a failed weather fetch (wttr.py's fail count
in $XDG_RUNTIME_DIR), it redraws the weather pill at once (back_online).
The panel (network_panel.py) and Settings import the helpers below.

Icons are written as escapes rather than literal Private-Use characters, for the
same reason fsstate.py does it: they do not survive being copied around.

Throughput is a delta, not a rate the kernel reports -- /proc/net/dev only ever
gives cumulative byte counts, so the first sample after startup has nothing to
subtract from and reports zero rather than a spike. That is why the first line
out of `watch` shows 0 B/s even on a busy link.
"""

import fcntl
import html
import json
import os
import select
import signal
import socket
import struct
import subprocess
import sys
import time

# Rates are averaged over INTERVAL, so 3 s reads as steadily as 1 s did.
INTERVAL = 3.0
# Everything run() fetches (route, addresses, DNS, Wi-Fi link) changes rarely,
# and spawning ip/resolvectl/iw for it every tick was most of this script's
# cost (~3 processes a second at the old 1 s). Answers are reused for this
# long; the counters behind the rates come from /proc and stay live.
CACHE_TTL = 15.0
_cache = {}

# watch: how often the pill is re-read without an `ip monitor` event.
WIFI_REFRESH = 30.0     # s: the signal percentage moves without any event
SAFETY_REFRESH = 300.0  # s: wired, or nothing at all
POLL = 5.0              # s: no `ip` to monitor with
SIOCGIFADDR = 0x8915
SIOCGIFNETMASK = 0x891B

ICON_WIFI = "\uf1eb"
ICON_GLOBE = "\uf0ac"
ICON_LINK = "\uf0c1"
ICON_ETHERNET = "\uf796"   # network-wired: a cable, the icon style's wired pill
ICON_VPN = "\uf3ed"        # shield-halved: a VPN / WireGuard tunnel is up
VPN_TYPES = ("vpn", "wireguard")
VPN_NAME_MAX = 14           # the pill has max-length 50; a long name is cut

# The theme's pill style: bar.network= in theme.conf, written by theme.py to
# waybar/generated/bar.conf as network=. "icon" (moe) is the interface's
# glyph alone -- Wi-Fi or a cable -- and the rest a hover away: the SSID and
# the signal ("Home · 70%"), the interface and address on a cable,
# "Available" while not connected but networks are in range, or
# "Disconnected". Empty: "Wi-Fi (70%) \uf1eb", no tooltip. Read on every
# build (one small file); theme.py sends SIGUSR1 when it changes.
# A bar on a narrow screen (barfit.py, asked once by watch) is "icon" in
# every theme: a laptop's bar has no room for "Wi-Fi (70%)".
BAR_CONF = os.path.expanduser("~/.config/waybar/generated/bar.conf")
STYLES = ("", "icon")
NARROW = False
# `watch --icon` (the dock and the taskbar): the glyph alone whatever the
# bar's style, so no address ends up on a tile.
FORCED_STYLE = ""


def bar_style(path=None):
    try:
        with open(path or BAR_CONF) as fh:
            for line in fh:
                key, _, value = line.strip().partition("=")
                if key == "network":
                    return value if value in STYLES else ""
    except OSError:
        pass
    return ""


def wifi_iface():
    """The first wireless interface, connected or not ("" with none)."""
    try:
        return next((n for n in sorted(os.listdir("/sys/class/net")) if is_wifi(n)), "")
    except OSError:
        return ""


def networks_in_range():
    """Does NetworkManager see any network with a name? Its last scan, not a
    new one (--rescan no): NetworkManager scans on its own while a radio is
    not connected. Cached like every other run()."""
    out = run(["nmcli", "-t", "-f", "SSID", "device", "wifi", "list", "--rescan", "no"])
    return any(line.strip() for line in out.splitlines())


def run(cmd, timeout=2):
    """Best-effort command runner, cached for CACHE_TTL. Returns "" rather than
    raising: every caller is decorating a tooltip, and a missing optional tool
    must not take the module down with it."""
    key = tuple(cmd)
    hit = _cache.get(key)
    now = time.monotonic()
    if hit and now - hit[0] < CACHE_TTL:
        return hit[1]
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=True
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        out = ""
    _cache[key] = (now, out)
    return out


def parse_route_table(text):
    """(iface, gateway) of the IPv4 default route with the lowest metric in a
    /proc/net/route text, or (None, None). The gateway is little-endian hex
    there: 0100A8C0 is 192.168.0.1."""
    best = None
    for line in text.splitlines()[1:]:
        f = line.split()
        if len(f) < 8 or f[1] != "00000000" or f[7] != "00000000":
            continue
        try:
            flags, metric = int(f[3], 16), int(f[6])
            gw = socket.inet_ntoa(struct.pack("<I", int(f[2], 16)))
        except (ValueError, struct.error):
            continue
        if not flags & 1:       # RTF_UP
            continue
        if best is None or metric < best[0]:
            best = (metric, f[0], None if gw == "0.0.0.0" else gw)
    return (best[1], best[2]) if best else (None, None)


def parse_ipv6_default(text):
    """The device of an IPv6 default route (::/0) in /proc/net/ipv6_route,
    for a v6-only link; None when there is none. Its gateway is not needed
    by the pill."""
    best = None
    for line in text.splitlines():
        f = line.split()
        if len(f) < 10 or f[0] != "0" * 32 or f[1] != "00" or f[9] == "lo":
            continue
        try:
            metric = int(f[5], 16)
        except ValueError:
            continue
        if best is None or metric < best[0]:
            best = (metric, f[9])
    return best[1] if best else None


def _read_text(path):
    try:
        with open(path) as fh:
            return fh.read()
    except OSError:
        return ""


def default_iface():
    """The interface carrying the default route, so the module follows a switch
    from ethernet to wifi without being told which to watch. Read from
    /proc/net/route (and ipv6_route): no `ip route` fork."""
    iface, gateway = parse_route_table(_read_text("/proc/net/route"))
    if iface:
        return iface, gateway
    iface = parse_ipv6_default(_read_text("/proc/net/ipv6_route"))
    if iface:
        return iface, None
    # No default route: fall back to any non-loopback interface that is up, so
    # a LAN-only link still reports something instead of reading as offline.
    try:
        for name in sorted(os.listdir("/sys/class/net")):
            if name == "lo":
                continue
            with open("/sys/class/net/%s/operstate" % name) as fh:
                if fh.read().strip() == "up":
                    return name, None
    except OSError:
        pass
    return None, None


def counters(iface):
    """rx/tx bytes, packets, errors, drops from /proc/net/dev."""
    try:
        with open("/proc/net/dev") as fh:
            for line in fh:
                if ":" not in line:
                    continue
                name, rest = line.split(":", 1)
                if name.strip() != iface:
                    continue
                f = rest.split()
                return {
                    "rx_bytes": int(f[0]), "rx_packets": int(f[1]),
                    "rx_errs": int(f[2]), "rx_drop": int(f[3]),
                    "tx_bytes": int(f[8]), "tx_packets": int(f[9]),
                    "tx_errs": int(f[10]), "tx_drop": int(f[11]),
                }
    except (OSError, ValueError, IndexError):
        pass
    return None


def addresses(iface):
    """IPv4 and IPv6 addresses, split by scope.

    A machine can hold several v6 addresses at once and they are not
    interchangeable: a link-local fe80:: cannot reach the internet, and a
    privacy-extension temporary address is the one outbound traffic actually
    uses. Lumping them into one line would be actively misleading, so they are
    kept apart and labelled.
    """
    v4, v6_global, v6_ula, v6_link = [], [], [], []
    out = run(["ip", "-j", "addr", "show", "dev", iface])
    if not out:
        return v4, v6_global, v6_ula, v6_link
    try:
        links = json.loads(out)
    except ValueError:
        return v4, v6_global, v6_ula, v6_link
    for link in links:
        for a in link.get("addr_info", []):
            addr, plen = a.get("local", ""), a.get("prefixlen", "")
            entry = "%s/%s" % (addr, plen)
            if a.get("family") == "inet":
                v4.append(entry)
            elif a.get("family") == "inet6":
                low = addr.lower()
                if low.startswith("fe80"):
                    v6_link.append(entry)
                elif low[:2] in ("fc", "fd"):
                    v6_ula.append(entry)
                else:
                    tag = " (temporary)" if a.get("temporary") else ""
                    v6_global.append(entry + tag)
    return v4, v6_global, v6_ula, v6_link


def link_info(iface):
    """Carrier speed, MTU, MAC. speed is absent or -1 for wifi and for a link
    with no carrier, which is not an error worth surfacing."""
    info = {}
    for key, path in (("speed", "speed"), ("mtu", "mtu"),
                      ("mac", "address"), ("state", "operstate")):
        try:
            with open("/sys/class/net/%s/%s" % (iface, path)) as fh:
                info[key] = fh.read().strip()
        except OSError:
            info[key] = ""
    return info


def dns_for(iface):
    out = run(["resolvectl", "dns", iface])
    # "Link 2 (enp7s0): 192.168.0.1" -> "192.168.0.1"
    if ":" in out:
        return out.split(":", 1)[1].strip()
    return ""


def wifi_info(iface):
    """SSID / signal / bitrate, empty for a wired link."""
    if not os.path.isdir("/sys/class/net/%s/wireless" % iface):
        return {}
    out = run(["iw", "dev", iface, "link"])
    info = {}
    for line in out.splitlines():
        line = line.strip()
        for key, prefix in (("ssid", "SSID:"), ("signal", "signal:"),
                            ("bitrate", "tx bitrate:"), ("freq", "freq:")):
            if line.startswith(prefix):
                info[key] = line[len(prefix):].strip()
    return info


def human_rate(bps):
    """Bytes per second in the largest unit that keeps it readable."""
    for unit, div in (("GB/s", 1 << 30), ("MB/s", 1 << 20), ("KB/s", 1 << 10)):
        if bps >= div:
            return "%.1f %s" % (bps / div, unit)
    return "%d B/s" % bps


def human_size(b):
    for unit, div in (("TB", 1 << 40), ("GB", 1 << 30),
                      ("MB", 1 << 20), ("KB", 1 << 10)):
        if b >= div:
            return "%.1f %s" % (b / div, unit)
    return "%d B" % b


def row(label, value):
    """One tooltip line. Values are escaped because they are not ours -- an
    SSID is free-form text and a stray & or < would break the pango parse and
    blank the whole tooltip, not just that line."""
    return "<b>%-8s</b> %s" % (label, html.escape(str(value)))


def first_ipv4(iface):
    """"192.168.0.10/24" for the interface's primary IPv4 address, from two
    ioctls (no `ip addr` fork), or "" when it has none."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            req = struct.pack("256s", iface.encode()[:15])
            addr = socket.inet_ntoa(fcntl.ioctl(sock.fileno(), SIOCGIFADDR, req)[20:24])
            mask = fcntl.ioctl(sock.fileno(), SIOCGIFNETMASK, req)[20:24]
    except OSError:
        return ""
    return "%s/%d" % (addr, bin(int.from_bytes(mask, "big")).count("1"))


def is_wifi(iface):
    return os.path.isdir("/sys/class/net/%s/wireless" % iface)


def signal_percent(signal):
    """iw's "-52 dBm" -> 96: the rough dBm->% curve waybar itself uses."""
    try:
        dbm = int(str(signal or "").split()[0])
    except (ValueError, IndexError):
        return None
    return max(0, min(100, 2 * (dbm + 100)))


def split_terse(line):
    """nmcli -t separates fields with ':' and escapes a literal one as '\\:'
    (a connection named "Office: VPN")."""
    fields, cur, i = [], "", 0
    while i < len(line):
        ch = line[i]
        if ch == "\\" and i + 1 < len(line):
            cur += line[i + 1]
            i += 2
            continue
        if ch == ":":
            fields.append(cur)
            cur = ""
        else:
            cur += ch
        i += 1
    fields.append(cur)
    return fields


def parse_active_vpns(text):
    """Names of the VPN and WireGuard connections in `nmcli -t -f NAME,TYPE
    connection show --active` output, in nmcli's order."""
    names = []
    for line in text.splitlines():
        fields = split_terse(line)
        if len(fields) >= 2 and fields[-1] in VPN_TYPES and fields[0]:
            names.append(fields[0])
    return names


def active_vpns():
    """The VPNs NetworkManager has up now ([] without nmcli). Cached like
    every run(): a watch event drops the cache, so a tunnel coming up --
    which adds an interface, so `ip monitor` reports it -- shows at once."""
    return parse_active_vpns(run(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show", "--active"]))


def vpn_suffix(vpns):
    """" <shield> name" for the pill ("+1" for each more), or "" with none."""
    if not vpns:
        return ""
    name = vpns[0] if len(vpns[0]) <= VPN_NAME_MAX else vpns[0][:VPN_NAME_MAX - 1] + "…"
    more = f" +{len(vpns) - 1}" if len(vpns) > 1 else ""
    return f" {ICON_VPN} {name}{more}"


def pill(iface, v4, wifi_signal=None, wifi=False, vpns=(), style="", ssid="",
         radio=False, available=False):
    """The pill's JSON from what it shows: the same text the full build()
    makes, without its tooltip. With a VPN up, its shield and name follow,
    and the class list gains "vpn". style "icon": the interface's glyph
    alone (class "icon": no width kept for a longer text), the SSID and signal (or the cable's address) as the tooltip;
    offline with a Wi-Fi radio (radio), the Wi-Fi glyph, "Available" when
    networks are in range."""
    if not iface:
        if style == "icon" and radio:
            return {"text": ICON_WIFI, "class": ["disconnected", "icon"],
                    "tooltip": "Available" if available else "Disconnected"}
        return {"text": ICON_GLOBE, "class": "disconnected"}
    if style == "icon" and wifi:
        pct = signal_percent(wifi_signal)
        tip = ssid or "Wi-Fi"
        out = {"text": ICON_WIFI, "class": ["connected", "icon"],
               "tooltip": html.escape(tip if pct is None else "%s · %d%%" % (tip, pct))}
    elif style == "icon":
        out = {"text": ICON_ETHERNET, "class": ["connected", "icon"],
               "tooltip": html.escape("%s · %s" % (iface, v4.split("/")[0]) if v4 else "%s (no IP)" % iface)}
    else:
        out = _pill_text(iface, v4, wifi_signal, wifi)
    if vpns:
        icon = ["icon"] if "icon" in (out["class"] if isinstance(out["class"], list) else [out["class"]]) else []
        out = dict(out, text=out["text"] + vpn_suffix(vpns), **{"class": ["connected", "vpn"] + icon})
    return out


def _pill_text(iface, v4, wifi_signal, wifi):
    if wifi:
        pct = signal_percent(wifi_signal)
        text = "Wi-Fi%s %s" % ("" if pct is None else " (%d%%)" % pct, ICON_WIFI)
    elif v4:
        text = "%s %s" % (v4, "\U0001f310")
    else:
        text = "%s (no IP) %s" % (iface, ICON_LINK)
    return {"text": text, "class": "connected"}


def current_pill():
    style = FORCED_STYLE or bar_style() or ("icon" if NARROW else "")
    iface, _gw = default_iface()
    if not iface or not counters(iface):
        radio = style == "icon" and bool(wifi_iface())
        return pill(None, "", style=style, radio=radio,
                    available=radio and networks_in_range())
    wifi = is_wifi(iface)
    info = wifi_info(iface) if wifi else {}
    return pill(iface, first_ipv4(iface), info.get("signal"), wifi, active_vpns(),
                style=style, ssid=info.get("ssid", ""))


def build(iface, gateway, prev, cur, elapsed):
    if not iface or not cur:
        return {
            "text": ICON_GLOBE,
            "tooltip": "Disconnected",
            "class": "disconnected",
        }

    v4, v6g, v6u, v6l = addresses(iface)
    link = link_info(iface)
    wifi = wifi_info(iface)
    dns = dns_for(iface)

    if prev and elapsed > 0:
        down = (cur["rx_bytes"] - prev["rx_bytes"]) / elapsed
        up = (cur["tx_bytes"] - prev["tx_bytes"]) / elapsed
        # A counter that went backwards means the interface was reset between
        # samples; report 0 rather than a negative or absurd rate.
        down = max(down, 0)
        up = max(up, 0)
    else:
        down = up = 0

    lines = []
    kind = "Wi-Fi" if wifi else "Ethernet"
    lines.append("<b>%s</b>  %s, %s" % (html.escape(iface), kind,
                                        html.escape(link.get("state", "?"))))
    lines.append("")

    lines.append(row("↓ down", human_rate(down)))
    lines.append(row("↑ up", human_rate(up)))
    lines.append("")

    lines.append(row("IPv4", v4[0] if v4 else "none"))
    for extra in v4[1:]:
        lines.append(row("", extra))

    # The interesting case on this machine is having none: the router hands out
    # link-local only, so there is no global v6 and anything v6-only is
    # unreachable. Saying "link-local only" is the useful answer, not fe80::.
    if v6g:
        lines.append(row("IPv6", v6g[0]))
        for extra in v6g[1:]:
            lines.append(row("", extra))
    elif v6u:
        lines.append(row("IPv6", "%s (ULA, no global)" % v6u[0]))
    elif v6l:
        lines.append(row("IPv6", "link-local only — no global address"))
        lines.append(row("", v6l[0]))
    else:
        lines.append(row("IPv6", "none"))

    if gateway:
        lines.append(row("Gateway", gateway))
    if dns:
        lines.append(row("DNS", dns))

    if wifi:
        lines.append("")
        if wifi.get("ssid"):
            lines.append(row("SSID", wifi["ssid"]))
        if wifi.get("signal"):
            lines.append(row("Signal", wifi["signal"]))
        if wifi.get("bitrate"):
            lines.append(row("Rate", wifi["bitrate"]))

    lines.append("")
    speed = link.get("speed", "")
    if speed and speed not in ("-1", "0"):
        lines.append(row("Link", "%s Mb/s, MTU %s" % (speed, link.get("mtu", "?"))))
    else:
        lines.append(row("Link", "MTU %s" % link.get("mtu", "?")))
    lines.append(row("MAC", link.get("mac", "?")))

    lines.append("")
    lines.append(row("Total", "↓ %s   ↑ %s" % (
        human_size(cur["rx_bytes"]), human_size(cur["tx_bytes"]))))
    # Errors and drops are cumulative since boot. Both being 0 is the normal and
    # boring case; a number climbing here is the first sign of a bad cable or a
    # saturated link, which is exactly what you go looking for in a hover.
    lines.append(row("Errors", "↓ %d   ↑ %d" % (
        cur["rx_errs"], cur["tx_errs"])))
    lines.append(row("Dropped", "↓ %d   ↑ %d" % (
        cur["rx_drop"], cur["tx_drop"])))

    if wifi:
        pct = ""
        try:
            dbm = int(str(wifi.get("signal", "")).split()[0])
            # Same rough dBm->% curve waybar itself uses.
            pct = " (%d%%)" % max(0, min(100, 2 * (dbm + 100)))
        except (ValueError, IndexError):
            pass
        text = "Wi-Fi%s %s" % (pct, ICON_WIFI)
    elif v4:
        text = "%s %s" % (v4[0], "\U0001f310")
    else:
        text = "%s (no IP) %s" % (iface, ICON_LINK)

    # <tt> because the bar's font is Red Hat Text, which is proportional: the
    # space-padded label column in row() only lines up in a monospace face, and
    # without this the whole table reads as ragged.
    return {
        "text": text,
        "tooltip": "<tt>" + "\n".join(lines) + "</tt>",
        "class": "connected",
    }


def emit(payload):
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def _die_with_parent():
    """Runs in the forked child before exec: the monitor gets SIGTERM when
    this script dies (waybar restarting the module), instead of living on
    until its next write hits a closed pipe."""
    import ctypes
    ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, 15)     # PR_SET_PDEATHSIG, SIGTERM


def monitor():
    """A long-running `ip monitor link address route`, or None without ip."""
    try:
        return subprocess.Popen(["ip", "monitor", "link", "address", "route"], stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                                preexec_fn=_die_with_parent)
    except OSError:
        return None


WEATHER_FAILS = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "waybar-weather.fails")


def is_connected(payload):
    """Is this pill payload a link that is up? Its class is "connected", or
    a list holding it (["connected", "vpn"] with a tunnel up)."""
    cls = payload.get("class")
    return cls == "connected" or (isinstance(cls, list) and "connected" in cls)


def back_online(before, after):
    """Did this change bring the link up (no default route -> one)?"""
    return before is not None and not is_connected(before) and is_connected(after)


def weather_retry():
    """The weather pill's last fetch failed (wttr.py keeps a count) and the
    link just came up: redraw it now instead of at its next retry."""
    if not os.path.exists(WEATHER_FAILS):
        return
    hypr = os.path.expanduser("~/.config/hypr/scripts")
    if hypr not in sys.path:
        sys.path.insert(0, hypr)
    try:
        import bar_signals
        bar_signals.poke("weather")
    except Exception:       # noqa: BLE001 - no bar: nothing to redraw
        pass


def watch():
    global NARROW
    try:
        import barfit
        NARROW = barfit.narrow()
    except Exception:       # noqa: BLE001 - the usual pill
        NARROW = False
    last_text = None
    last_payload = None
    mon = monitor()
    # theme.py's SIGUSR1 (bar.network changed) ends the wait below at once:
    # the signal writes a byte into `wake`, which the select watches too.
    wake, wake_w = os.pipe()
    os.set_blocking(wake, False)
    os.set_blocking(wake_w, False)
    signal.set_wakeup_fd(wake_w)
    signal.signal(signal.SIGUSR1, lambda *_: None)
    while True:
        # A watcher has to outlive its own errors: an exception here used to
        # end the pill for the rest of the session. One bad sample becomes an
        # "error" pill and the next event tries again.
        try:
            payload = current_pill()
        except Exception as exc:  # noqa: BLE001 - deliberately broad, see above
            payload = {"text": ICON_GLOBE, "tooltip": f"network.py: {exc}", "class": "error"}
        if back_online(last_payload, payload):
            weather_retry()
        last_payload = payload
        line = json.dumps(payload)
        if line != last_text:
            try:
                emit(payload)
            except BrokenPipeError:
                return          # waybar went away; nothing left to talk to
            last_text = line
        # Both styles carry the glyph; "icon" offline too, to follow the
        # networks coming into range.
        wifi = ICON_WIFI in payload.get("text", "")
        wait = WIFI_REFRESH if wifi else SAFETY_REFRESH
        if mon is None or mon.poll() is not None:
            time.sleep(POLL)
            mon = monitor() if mon is not None else None
            continue
        fd = mon.stdout.fileno()
        ready = select.select([fd, wake], [], [], wait)[0]
        if wake in ready:
            while True:
                try:
                    if not os.read(wake, 64):
                        break
                except BlockingIOError:
                    break
        if fd in ready:
            if not os.read(fd, 65536):
                mon = monitor()
                continue
            # A change comes as a burst of lines (link, addresses, routes):
            # let it settle, then read once. The cached `iw` answer is
            # dropped so a new network shows its own signal.
            while select.select([fd], [], [], 0.3)[0]:
                if not os.read(fd, 65536):
                    break
            _cache.clear()


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "watch"

    if mode == "watch":
        global FORCED_STYLE
        FORCED_STYLE = "icon" if "--icon" in sys.argv[2:] else ""
        watch()
        return

    iface, gw = default_iface()
    prev = counters(iface) if iface else None
    last = time.monotonic()
    time.sleep(INTERVAL)
    iface, gw = default_iface()
    cur = counters(iface) if iface else None
    emit(build(iface, gw, prev, cur, time.monotonic() - last))


if __name__ == "__main__":
    main()
