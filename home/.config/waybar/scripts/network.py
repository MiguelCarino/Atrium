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
    network.py once     one JSON line and exit, for testing

Icons are written as escapes rather than literal Private-Use characters, for the
same reason fsstate.py does it: they do not survive being copied around.

Throughput is a delta, not a rate the kernel reports -- /proc/net/dev only ever
gives cumulative byte counts, so the first sample after startup has nothing to
subtract from and reports zero rather than a spike. That is why the first line
out of `watch` shows 0 B/s even on a busy link.
"""

import html
import json
import os
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

ICON_WIFI = "\uf1eb"
ICON_GLOBE = "\uf0ac"
ICON_LINK = "\uf0c1"


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


def default_iface():
    """The interface carrying the default route, so the module follows a switch
    from ethernet to wifi without being told which to watch."""
    out = run(["ip", "-j", "route", "show", "default"])
    if out:
        try:
            routes = json.loads(out)
            if routes:
                return routes[0].get("dev"), routes[0].get("gateway")
        except ValueError:
            pass
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


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "watch"

    iface, gw = default_iface()
    prev = counters(iface) if iface else None
    last = time.monotonic()

    if mode == "once":
        time.sleep(INTERVAL)
        iface, gw = default_iface()
        cur = counters(iface) if iface else None
        emit(build(iface, gw, prev, cur, time.monotonic() - last))
        return

    emit(build(iface, gw, None, prev, 0))
    prev_iface = iface
    while True:
        time.sleep(INTERVAL)
        now = time.monotonic()
        # A watcher has to outlive its own errors: an exception here used to
        # end the pill for the rest of the session. One bad sample becomes an
        # "error" pill and the next tick tries again.
        try:
            iface, gw = default_iface()
            cur = counters(iface) if iface else None
            # Default route moved to another interface (Ethernet <-> Wi-Fi):
            # the previous counters belong to the old NIC, and subtracting them
            # would report a bogus spike. Start the delta over instead.
            if iface != prev_iface:
                prev = None
            emit(build(iface, gw, prev, cur, now - last))
        except BrokenPipeError:
            return          # waybar went away; nothing left to talk to
        except Exception as exc:  # noqa: BLE001 - deliberately broad, see above
            emit({"text": ICON_GLOBE, "tooltip": f"network.py: {exc}",
                  "class": "error"})
            cur = None
        prev, last, prev_iface = cur, now, iface

if __name__ == "__main__":
    main()
