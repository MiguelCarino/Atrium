#!/usr/bin/env python3
"""Network & Bluetooth settings: one command line for everything the
Settings page "Network & Bluetooth" does, so the search bar, a key or a
terminal can do the same.

    network-settings.py status                 JSON: hostname, connectivity, airplane mode,
                                               the Wi-Fi radio, every network device with its
                                               addresses / gateway / DNS / speed / traffic, and
                                               every saved connection (wired, Wi-Fi, VPN)
    network-settings.py wifi on|off|toggle     the Wi-Fi radio
    network-settings.py wifi-list [--rescan]   JSON: the Wi-Fi networks in range, one row per
                                               name (the strongest access point), saved ones marked
    network-settings.py wifi-connect SSID [--hidden] [--password-stdin]
                                               join a network; the password is read from stdin
                                               (never from the command line, where every process
                                               could read it) and saved with the profile
    network-settings.py up|down UUID           bring a saved connection up / down (a VPN, a Wi-Fi
                                               network, the wired profile)
    network-settings.py device-connect DEV     let NetworkManager connect a device again
    network-settings.py forget UUID            delete a saved connection
    network-settings.py autoconnect UUID on|off
    network-settings.py vpn-import FILE        an OpenVPN .ovpn or a WireGuard .conf from your provider
    network-settings.py airplane on|off|toggle|status
    network-settings.py hostname [NAME]        print it, or rename this computer (asks for your
                                               password through the polkit agent)

    network-settings.py bt status              JSON: the adapter (power, visible, scanning) and
                                               every device it knows, battery where reported
    network-settings.py bt power on|off|toggle
    network-settings.py bt discoverable on|off
    network-settings.py bt scan [SECONDS]      look for new devices (default 12 s)
    network-settings.py bt pair MAC            pair, trust (so it reconnects by itself), connect
    network-settings.py bt connect|disconnect|remove MAC

Actions print one line saying what happened and exit 0, or print the reason
on stderr and exit 1 -- the Settings page shows that line under the row.

Where things are kept, so they survive a Hyprland reload, a re-login and a
reboot -- nothing is kept here:
  * Wi-Fi radio and saved connections: NetworkManager's own state
    (/var/lib/NetworkManager, /etc/NetworkManager/system-connections).
  * Bluetooth off is BOTH "bluetoothctl power off" AND an rfkill soft block:
    BlueZ powers an unblocked adapter back on at boot (AutoEnable), while
    systemd-rfkill restores the block, so "off" stays off. On unblocks first.
  * Airplane mode is "rfkill block all" (systemd-rfkill restores it at boot).
    Before blocking, which radios were on is written to
    $XDG_STATE_HOME/hypr/airplane.json, and turning airplane mode off puts
    exactly those back (both on when nothing was saved). Airplane mode reads
    as "on" whenever every radio is soft-blocked, however it got that way --
    the same rule GNOME uses. The wired network is never touched.
  * Discoverable is temporary on purpose: BlueZ ends it by itself after its
    DiscoverableTimeout (3 minutes here).
  * The hostname is systemd-hostnamed's (/etc/hostname).

Reading uses nmcli and BlueZ's D-Bus object list (one call for the adapter
and every device, battery included); the Bluetooth actions use bluetoothctl,
like the launcher's "bluetooth on". Pairing registers a NoInputNoOutput
agent: with that, headphones, mice, keyboards and phones all pair with
"Just Works" and nothing has to be typed or confirmed on this side. Joining
a Wi-Fi network goes over NetworkManager's D-Bus API
(AddAndActivateConnection) so the password travels inside the call and lands
in the saved profile; a profile that fails to connect (wrong password, out of
range) is deleted again, and on success older profiles for the same name are
replaced, so "Forget" never has duplicates to deal with.
"""
import json
import os
import re
import subprocess
import sys
import time

WAYBAR = os.path.expanduser("~/.config/waybar/scripts")
sys.path.insert(0, WAYBAR)
try:
    import network as netinfo  # the network pill's script: counters, addresses (scope-split IPv6), link info
except ImportError:            # (keeps working without the bar, just with fewer details)
    netinfo = None

STATE_DIR = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "hypr")
AIRPLANE_STATE = os.path.join(STATE_DIR, "airplane.json")
CONNECT_TIMEOUT = 45          # seconds to wait for a Wi-Fi network to come up (DHCP included)
SCAN_SECONDS = 12

HIDDEN_TYPES = {"loopback", "bridge", "tun", "bond", "team", "dummy", "veth", "vlan"}
VPN_TYPES = {"vpn", "wireguard"}
NM = "org.freedesktop.NetworkManager"
NM_PATH = "/org/freedesktop/NetworkManager"

# NetworkManager's NMDeviceStateReason numbers that a person can act on.
FAIL_REASONS = {7: "it needs a password", 8: "wrong password?", 9: "the network refused the settings",
                10: "the Wi-Fi driver gave up", 11: "no answer from the network -- wrong password?",
                5: "no address from the network (DHCP)", 53: "the network is not in range",
                63: "it was cancelled"}


# -- small pure helpers (tested in tests/test_settings_network.py) -------------------
def split_terse(line):
    """nmcli -t separates fields with ':' and escapes literal ones as '\\:'
    (the same rule network_panel.py splits on)."""
    return [f.replace("\\:", ":").replace("\\\\", "\\") for f in re.split(r"(?<!\\):", line)]


def parse_multiline(text):
    """`nmcli -t device show DEV`: FIELD:value lines, values NOT escaped,
    repeated fields as FIELD[1], FIELD[2]... -> {FIELD: value or [values]}."""
    out = {}
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        m = re.fullmatch(r"(.+)\[\d+\]", key)
        if m:
            out.setdefault(m[1], []).append(value)
        else:
            out[key] = value
    return out


def security_kind(security):
    """nmcli's SECURITY column ('', 'WPA2', 'WPA1 WPA2', 'WPA3', 'WPA2 802.1X',
    'WEP', 'OWE'...) -> 'open', 'psk', 'enterprise', 'wep' or 'owe'. Only open,
    owe and psk can be joined from the page; the others need the connection
    editor (certificates, user names)."""
    s = (security or "").upper().split()
    if "802.1X" in s:
        return "enterprise"
    if "WEP" in s:
        return "wep"
    if any(w.startswith("WPA") for w in s):
        return "psk"
    if "OWE" in s:
        return "owe"
    return "open"


def bars(signal):
    """0-100 -> four signal bars, the way nmcli draws them."""
    n = 4 if signal >= 80 else 3 if signal >= 55 else 2 if signal >= 30 else 1 if signal > 5 else 0
    return "▂▄▆█"[:n] + "_" * (4 - n)


def parse_wifi_list(text, saved):
    """`nmcli -t -f IN-USE,SSID,BSSID,SIGNAL,SECURITY,CHAN,RATE device wifi list`
    -> one entry per network name, the strongest access point's numbers, the
    in-use one first and then by signal. Hidden networks (no name) are left
    out -- they are joined by typing their name. saved: {ssid: uuid}."""
    best = {}
    for line in text.splitlines():
        f = split_terse(line)
        if len(f) < 7 or not f[1]:
            continue
        in_use, ssid, _bssid, signal, security, chan, rate = f[:7]
        try:
            signal = int(signal)
        except ValueError:
            signal = 0
        entry = {"ssid": ssid, "signal": signal, "bars": bars(signal), "security": security or "open",
                 "kind": security_kind(security), "chan": chan, "rate": rate,
                 "band": "5 GHz" if chan.isdigit() and int(chan) > 14 else "2.4 GHz" if chan.isdigit() else "",
                 "in_use": in_use.strip() == "*", "saved": saved.get(ssid)}
        old = best.get(ssid)
        if (old is None or (entry["in_use"] and not old["in_use"])
                or (entry["in_use"] == old["in_use"] and signal > old["signal"])):
            best[ssid] = entry
    return sorted(best.values(), key=lambda e: (not e["in_use"], -e["signal"], e["ssid"].lower()))


def rfkill_airplane(devices):
    """rfkill -J's device list -> True when there is at least one radio and
    every one is soft-blocked (airplane mode, however it was reached)."""
    return bool(devices) and all(d.get("soft") == "blocked" for d in devices)


HOSTNAME_RE = re.compile(r"(?!-)[A-Za-z0-9-]{1,63}(?<!-)")


def valid_hostname(name):
    """A static hostname: dot-separated labels of letters, digits and inner
    hyphens, each 1-63 long, 64 characters at most (Linux's HOST_NAME_MAX)."""
    return bool(name) and len(name) <= 64 and all(HOSTNAME_RE.fullmatch(p) for p in name.split("."))


def vpn_file_type(path, text):
    """Which NetworkManager importer reads this file: 'wireguard' for a
    wg-quick .conf ([Interface] + PrivateKey), 'openvpn' for .ovpn or any
    file with OpenVPN's 'remote'/'client' lines, None when neither."""
    low = text.lower()
    if "[interface]" in low and "privatekey" in low:
        return "wireguard"
    if path.lower().endswith(".ovpn") or re.search(r"^\s*(remote|client)\b", low, re.M):
        return "openvpn"
    return None


def bt_devices(objects):
    """BlueZ GetManagedObjects (unpacked) -> the adapter's properties and its
    devices: paired first (connected on top), then the ones a scan found,
    strongest first. Unnamed devices that only advertise (beacons, TVs'
    remotes from next door) are left out of the found list."""
    adapter, devices = {}, []
    for path, ifaces in objects.items():
        if "org.bluez.Adapter1" in ifaces and not adapter:
            adapter = dict(ifaces["org.bluez.Adapter1"], path=path)
        dev = ifaces.get("org.bluez.Device1")
        if not dev:
            continue
        battery = ifaces.get("org.bluez.Battery1", {}).get("Percentage")
        name = dev.get("Alias") or dev.get("Name") or ""
        mac = dev.get("Address", "")
        if not dev.get("Paired") and (not dev.get("Name") or name.replace("-", ":").upper() == mac.upper()):
            continue
        devices.append({"mac": mac, "name": name or mac, "icon": dev.get("Icon", ""),
                        "paired": bool(dev.get("Paired")), "connected": bool(dev.get("Connected")),
                        "trusted": bool(dev.get("Trusted")), "blocked": bool(dev.get("Blocked")),
                        "battery": int(battery) if battery is not None else None,
                        "rssi": dev.get("RSSI")})
    devices.sort(key=lambda d: (not d["paired"], not d["connected"],
                                -(d["rssi"] if d["rssi"] is not None else -999), d["name"].lower()))
    return adapter, devices


def wifi_settings(ssid, password=None, hidden=False):
    """The connection settings sent to AddAndActivateConnection, as plain
    Python ({setting: {key: value}}). For a network in range only the
    password goes in: NetworkManager fills in the security type from the
    access point (what `nmcli device wifi connect` does too). A hidden
    network has no access point to read it from, so a password means WPA."""
    conn = {"connection": {"id": ssid, "type": "802-11-wireless", "autoconnect": True},
            "802-11-wireless": {"ssid": ssid.encode(), "mode": "infrastructure"}}
    if hidden:
        conn["802-11-wireless"]["hidden"] = True
    if password:
        conn["802-11-wireless-security"] = {"psk": password}
        if hidden:
            conn["802-11-wireless-security"]["key-mgmt"] = "wpa-psk"
    return conn


# -- running things -------------------------------------------------------------------
def sh(*cmd, timeout=15, stdin=None):
    """(ok, stdout, last line of stderr) -- never raises."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, input=stdin)
    except subprocess.TimeoutExpired:
        return False, "", "timed out"
    except OSError as exc:
        return False, "", str(exc)
    err = [l for l in p.stderr.strip().splitlines() if l.strip()]
    return p.returncode == 0, p.stdout, (err[-1].removeprefix("Error: ") if err else "")


def nmcli(*args, timeout=15):
    return sh("nmcli", *args, timeout=timeout)


def done(ok, message):
    """Finish an action: the line on stdout (ok) or stderr (not), exit 0/1."""
    print(message, file=sys.stdout if ok else sys.stderr)
    sys.exit(0 if ok else 1)


# -- NetworkManager -------------------------------------------------------------------
def connections():
    ok, out, _ = nmcli("-t", "-f", "NAME,UUID,TYPE,DEVICE,ACTIVE,STATE,AUTOCONNECT,TIMESTAMP", "connection", "show")
    rows = []
    for line in out.splitlines():
        f = split_terse(line)
        if len(f) < 8 or f[2] in HIDDEN_TYPES:
            continue
        row = {"name": f[0], "uuid": f[1], "type": f[2], "device": f[3], "active": f[4] == "yes",
               "state": f[5], "autoconnect": f[6] == "yes", "last_used": int(f[7]) if f[7].isdigit() else 0}
        if row["type"] == "802-11-wireless":
            _, ssid, _ = nmcli("-g", "802-11-wireless.ssid", "connection", "show", row["uuid"])
            row["ssid"] = ssid.strip().replace("\\:", ":")
        if row["type"] == "vpn":
            _, kind, _ = nmcli("-g", "vpn.service-type", "connection", "show", row["uuid"])
            row["vpn_kind"] = kind.strip().rsplit(".", 1)[-1]          # openvpn, openconnect...
        rows.append(row)
    rows.sort(key=lambda c: (c["type"] != "802-3-ethernet", not c["active"], -c["last_used"], c["name"].lower()))
    return rows


def device_details(dev, dtype):
    _, out, _ = nmcli("-t", "device", "show", dev)
    info = parse_multiline(out)

    def many(key):
        v = info.get(key, [])
        return v if isinstance(v, list) else [v] if v else []

    d = {"name": dev, "type": dtype, "state": info.get("GENERAL.STATE", "").split("(")[-1].rstrip(")"),
         "connection": info.get("GENERAL.CONNECTION", ""), "mac": info.get("GENERAL.HWADDR", ""),
         "ipv4": many("IP4.ADDRESS"), "gateway": info.get("IP4.GATEWAY", ""),
         "ipv6": many("IP6.ADDRESS"), "gateway6": info.get("IP6.GATEWAY", ""),
         "dns": many("IP4.DNS") + many("IP6.DNS"), "speed": None, "rx": None, "tx": None}
    if netinfo:
        link = netinfo.link_info(dev)
        if link.get("speed", "").lstrip("-").isdigit() and int(link["speed"]) > 0:
            d["speed"] = f"{int(link['speed'])} Mb/s"
        _v4, g, u, l = netinfo.addresses(dev)
        if g or u or l:
            d["ipv6"] = g + [a + " (ULA)" for a in u] + [a + " (link-local)" for a in l]
        c = netinfo.counters(dev)
        if c:
            d["rx"], d["tx"] = netinfo.human_size(c["rx_bytes"]), netinfo.human_size(c["tx_bytes"])
    return d


def status():
    _, radio, _ = nmcli("-t", "-f", "WIFI-HW,WIFI", "radio")
    hw, _, sw = radio.strip().partition(":")
    _, conn_state, _ = nmcli("networking", "connectivity")
    _, net_on, _ = nmcli("networking")
    _, devs, _ = nmcli("-t", "-f", "DEVICE,TYPE,STATE", "device")
    devices, wifi_dev = [], None
    for line in devs.splitlines():
        f = split_terse(line)
        if len(f) < 3 or f[1] not in ("ethernet", "wifi"):
            continue
        if f[1] == "wifi" and wifi_dev is None:
            wifi_dev = f[0]
        devices.append(device_details(f[0], f[1]))
    route = sh("ip", "-j", "route", "show", "default")[1]
    try:
        default = (json.loads(route) or [{}])[0].get("dev")
    except (ValueError, IndexError):
        default = None
    rf = rfkill()
    return {"hostname": hostname(), "networking": net_on.strip() == "enabled",
            "connectivity": conn_state.strip() or "unknown", "default_iface": default,
            "wifi": {"hardware": hw == "enabled", "radio": sw == "enabled", "device": wifi_dev},
            "airplane": rfkill_airplane(rf), "rfkill": rf, "devices": devices, "connections": connections()}


def wifi_list(rescan=False):
    saved = {c.get("ssid"): c["uuid"] for c in connections() if c["type"] == "802-11-wireless"}
    _, out, _ = nmcli("-t", "-f", "IN-USE,SSID,BSSID,SIGNAL,SECURITY,CHAN,RATE", "device", "wifi", "list",
                      "--rescan", "yes" if rescan else "auto", timeout=30)
    return parse_wifi_list(out, saved)


def wifi_connect(ssid, password=None, hidden=False):
    """AddAndActivateConnection over D-Bus, then wait for it to come up."""
    from gi.repository import Gio, GLib

    def call(path, iface, method, args=None, reply=None):
        return bus.call_sync(NM, path, iface, method, args, GLib.VariantType(reply) if reply else None,
                             Gio.DBusCallFlags.NONE, 30000, None).unpack()

    def prop(path, iface, name):
        return call(path, "org.freedesktop.DBus.Properties", "Get", GLib.Variant("(ss)", (iface, name)), "(v)")[0]

    _, devs, _ = nmcli("-t", "-f", "DEVICE,TYPE", "device")
    iface = next((f[0] for f in map(split_terse, devs.splitlines()) if len(f) > 1 and f[1] == "wifi"), None)
    if not iface:
        done(False, "no Wi-Fi device")
    try:                                            # NetworkManager not answering: a reason, not a traceback
        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        dev_path = call(NM_PATH, NM, "GetDeviceByIpIface", GLib.Variant("(s)", (iface,)), "(o)")[0]
        aps = [] if hidden else call(dev_path, NM + ".Device.Wireless", "GetAllAccessPoints", None, "(ao)")[0]
    except GLib.Error as exc:
        done(False, "NetworkManager did not answer: " + (exc.message.split(":")[-1].strip() or "D-Bus error"))
    ap_path = "/"
    if not hidden:
        best = -1
        for ap in aps:
            try:
                name = bytes(prop(ap, NM + ".AccessPoint", "Ssid")).decode(errors="replace")
                strength = prop(ap, NM + ".AccessPoint", "Strength")
            except Exception:                       # an access point that just went away
                continue
            if name == ssid and strength > best:
                ap_path, best = ap, strength
        if ap_path == "/":
            done(False, f"{ssid} is not in range (try Rescan)")
    old = [c["uuid"] for c in connections() if c["type"] == "802-11-wireless" and c.get("ssid") == ssid]

    def variant(value):
        if isinstance(value, bool):
            return GLib.Variant("b", value)
        if isinstance(value, bytes):
            return GLib.Variant("ay", value)
        return GLib.Variant("s", value)

    settings = GLib.Variant("a{sa{sv}}", {s: {k: variant(v) for k, v in kv.items()}
                                          for s, kv in wifi_settings(ssid, password, hidden).items()})
    try:
        new_path, active = bus.call_sync(NM, NM_PATH, NM, "AddAndActivateConnection",
                                         GLib.Variant.new_tuple(settings, GLib.Variant("o", dev_path),
                                                                GLib.Variant("o", ap_path)),
                                         GLib.VariantType("(oo)"), Gio.DBusCallFlags.NONE, 30000, None).unpack()
    except GLib.Error as exc:
        done(False, exc.message.split(":")[-1].strip() or "NetworkManager refused it")
    end = time.monotonic() + CONNECT_TIMEOUT
    state = 1
    while time.monotonic() < end:
        try:
            state = prop(active, NM + ".Connection.Active", "State")
        except GLib.Error:                          # the active connection is gone: it failed
            state = 4
        if state in (2, 4):
            break
        time.sleep(0.5)
    if state == 2:
        for uuid in old:                            # replace the older profiles for this name
            nmcli("connection", "delete", "uuid", uuid)
        done(True, f"connected to {ssid}")
    try:
        reason = prop(dev_path, NM + ".Device", "StateReason")[1]
    except GLib.Error:
        reason = 0
    try:                                            # a profile that never worked is not worth keeping
        call(new_path, NM + ".Settings.Connection", "Delete")
    except GLib.Error:
        pass
    done(False, f"could not join {ssid}: " + FAIL_REASONS.get(reason, "it did not come up" if state != 1
                                                               else "timed out"))


# -- radios ---------------------------------------------------------------------------
def rfkill():
    ok, out, _ = sh("rfkill", "-J")
    try:
        data = json.loads(out) if ok else {}
    except ValueError:
        data = {}
    return [{"type": d.get("type"), "soft": d.get("soft"), "hard": d.get("hard")}
            for d in data.get("rfkilldevices", [])]


def airplane(mode):
    on = rfkill_airplane(rfkill())
    if mode == "status":
        print("on" if on else "off")
        return
    want = (not on) if mode == "toggle" else mode == "on"
    if want:
        before = {"wifi": nmcli("radio", "wifi")[1].strip() == "enabled", "bluetooth": bt_powered()}
        if not on:                                  # do not overwrite what was saved last time
            os.makedirs(STATE_DIR, exist_ok=True)
            tmp = AIRPLANE_STATE + ".tmp"           # atomic, like every other state write here
            with open(tmp, "w") as fh:
                json.dump(before, fh)
            os.replace(tmp, AIRPLANE_STATE)
        ok, _, err = sh("rfkill", "block", "all")
        done(ok, "airplane mode on: Wi-Fi and Bluetooth are off" if ok else err or "rfkill failed")
    try:
        with open(AIRPLANE_STATE) as fh:
            before = json.load(fh)
    except (OSError, ValueError):
        before = {"wifi": True, "bluetooth": True}
    ok, _, err = sh("rfkill", "unblock", "all")
    if not ok:
        done(False, err or "rfkill failed")
    nmcli("radio", "wifi", "on" if before.get("wifi", True) else "off")
    if before.get("bluetooth", True):
        time.sleep(0.5)                             # the adapter needs a moment after the unblock
        sh("bluetoothctl", "power", "on")
    else:
        sh("rfkill", "block", "bluetooth")
    try:
        os.remove(AIRPLANE_STATE)
    except OSError:
        pass
    done(True, "airplane mode off: " + ", ".join(
        f"{k} {'on' if before.get(k, True) else 'off'}" for k in ("wifi", "bluetooth")).replace("wifi", "Wi-Fi")
        .replace("bluetooth", "Bluetooth"))


def hostname(new=None):
    if new is None:
        try:
            with open("/proc/sys/kernel/hostname") as fh:
                return fh.read().strip()
        except OSError:
            return os.uname().nodename
    if not valid_hostname(new):
        done(False, "letters, digits and hyphens only (no spaces), up to 63 per part")
    ok, _, err = sh("hostnamectl", "hostname", new, timeout=180)    # polkit asks for the password
    done(ok, f"this computer is now called {new}" if ok else err or "not changed")


# -- Bluetooth ------------------------------------------------------------------------
def bt_objects():
    from gi.repository import Gio, GLib
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        return bus.call_sync("org.bluez", "/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects", None,
                             GLib.VariantType("(a{oa{sa{sv}}})"), Gio.DBusCallFlags.NONE, 3000,
                             None).unpack()[0]
    except GLib.Error:
        return None


def bt_status():
    objects = bt_objects()
    if objects is None:
        return {"present": False, "service": False, "devices": []}
    adapter, devices = bt_devices(objects)
    blocked = any(d["type"] == "bluetooth" and d["soft"] == "blocked" for d in rfkill())
    hard = any(d["type"] == "bluetooth" and d["hard"] == "blocked" for d in rfkill())
    return {"present": bool(adapter), "service": True, "powered": bool(adapter.get("Powered")),
            "blocked": blocked, "hard_blocked": hard, "state": adapter.get("PowerState", ""),
            "discoverable": bool(adapter.get("Discoverable")),
            "discoverable_timeout": adapter.get("DiscoverableTimeout", 0),
            "pairable": bool(adapter.get("Pairable")), "discovering": bool(adapter.get("Discovering")),
            "name": adapter.get("Alias") or adapter.get("Name", ""), "address": adapter.get("Address", ""),
            "devices": devices}


def bt_known(mac):
    """Does BlueZ still have this device? A device a scan found but that was
    never paired is dropped again TemporaryTimeout (30 s) after the scan
    ends, and pairing an address BlueZ no longer has fails with "not
    available" -- so Pair a minute after Look for devices must look again."""
    objects = bt_objects() or {}
    return any(i.get("org.bluez.Device1", {}).get("Address", "").upper() == mac.upper() for i in objects.values())


def bt_powered():
    s = bt_status()
    return bool(s.get("powered"))


def btctl(*args, timeout=15):
    """bluetoothctl one-shot; its errors come on stdout, coloured."""
    ok, out, err = sh("bluetoothctl", *args, timeout=timeout + 5)
    text = re.sub(r"\x1b\[[0-9;]*m|\x01|\x02", "", out)
    fail = next((l.strip() for l in text.splitlines() if re.search(r"Failed|not available|Error|No default", l)),
                "")
    return ok and not fail, text, (fail or err)


def bt(args):
    if not args:
        done(False, "bt status|power|discoverable|scan|pair|connect|disconnect|remove")
    cmd, rest = args[0], args[1:]
    if cmd == "status":
        print(json.dumps(bt_status()))
        return
    if cmd == "power":
        mode = rest[0] if rest else "toggle"
        want = (not bt_powered()) if mode == "toggle" else mode == "on"
        if want:
            sh("rfkill", "unblock", "bluetooth")
            for _ in range(20):                     # the controller re-appears unblocked
                if "off-blocked" not in bt_status().get("state", ""):
                    break
                time.sleep(0.15)
            ok, _, err = btctl("power", "on")
            done(ok, "Bluetooth on" if ok else err or "could not turn Bluetooth on")
        btctl("power", "off")
        ok, _, err = sh("rfkill", "block", "bluetooth")
        done(ok, "Bluetooth off" if ok else err)
    if cmd == "discoverable":
        on = (rest[0] if rest else "on") == "on"
        if on:
            btctl("pairable", "on")
        ok, _, err = btctl("discoverable", "on" if on else "off")
        done(ok, ("visible to other devices for a few minutes" if on else "hidden") if ok else err)
    if cmd == "scan":
        secs = int(rest[0]) if rest and rest[0].isdigit() else SCAN_SECONDS
        ok, _, err = btctl("--timeout", str(secs), "scan", "on", timeout=secs)
        found = [d for d in bt_status().get("devices", []) if not d["paired"]]
        done(True, f"{len(found)} device{'s' if len(found) != 1 else ''} found")
    if cmd in ("pair", "connect", "disconnect", "remove"):
        if not rest or not re.fullmatch(r"([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", rest[0]):
            done(False, "needs the device's address, like AA:BB:CC:DD:EE:FF")
        mac = rest[0]
        if cmd == "pair":
            if not bt_known(mac):                   # forgotten since the scan: find it again first
                for _ in range(2):
                    btctl("--timeout", "6", "scan", "on", timeout=6)
                    if bt_known(mac):
                        break
                else:
                    done(False, "the device is not answering: put it in pairing mode, then Pair again")
            btctl("trust", mac)
            ok, _, err = btctl("--agent", "NoInputNoOutput", "--timeout", "40", "pair", mac, timeout=40)
            if not ok and "AlreadyExists" not in err:
                done(False, "pairing failed: " + err.split(":")[-1].strip() if err else "pairing failed")
            ok, _, err = btctl("--timeout", "20", "connect", mac, timeout=20)
            done(True, "paired and connected" if ok else "paired (connect it when it is in range)")
        ok, _, err = btctl("--timeout", "20", cmd, mac, timeout=20)
        word = {"connect": "connected", "disconnect": "disconnected", "remove": "removed"}[cmd]
        done(ok, word if ok else f"{cmd} failed: " + (err.split(":")[-1].strip() or "no answer"))
    done(False, f"unknown bt command {cmd}")


# -- command line ---------------------------------------------------------------------
def main(argv):
    if not argv:
        print(__doc__)
        return
    cmd, rest = argv[0], argv[1:]
    if cmd == "status":
        print(json.dumps(status()))
    elif cmd == "wifi":
        mode = rest[0] if rest else "toggle"
        if mode == "toggle":
            mode = "off" if nmcli("radio", "wifi")[1].strip() == "enabled" else "on"
        if mode == "on":
            sh("rfkill", "unblock", "wlan")          # a radio rfkill-blocked by airplane mode stays dead otherwise
        ok, _, err = nmcli("radio", "wifi", mode)
        done(ok, f"Wi-Fi {mode}" if ok else err)
    elif cmd == "wifi-list":
        print(json.dumps(wifi_list("--rescan" in rest)))
    elif cmd == "wifi-connect":
        if not rest:
            done(False, "wifi-connect SSID [--hidden] [--password-stdin]")
        password = sys.stdin.readline().rstrip("\n") if "--password-stdin" in rest else None
        wifi_connect(rest[0], password or None, "--hidden" in rest)
    elif cmd in ("up", "down"):
        if not rest:
            done(False, f"{cmd} UUID")
        ok, _, err = nmcli("connection", cmd, "uuid", rest[0], timeout=CONNECT_TIMEOUT + 15)
        if not ok and "secrets were required" in err.lower():
            err = "it needs a password: open Edit…, save the password there, then try again"
        done(ok, ("connected" if cmd == "up" else "disconnected") if ok else err)
    elif cmd == "device-connect":
        ok, _, err = nmcli("device", "connect", rest[0] if rest else "", timeout=CONNECT_TIMEOUT + 15)
        done(ok, "connected" if ok else err)
    elif cmd == "forget":
        ok, _, err = nmcli("connection", "delete", "uuid", rest[0] if rest else "")
        done(ok, "forgotten" if ok else err)
    elif cmd == "autoconnect":
        if len(rest) < 2:
            done(False, "autoconnect UUID on|off")
        ok, _, err = nmcli("connection", "modify", "uuid", rest[0], "connection.autoconnect",
                           "yes" if rest[1] == "on" else "no")
        done(ok, f"auto-connect {rest[1]}" if ok else err)
    elif cmd == "vpn-import":
        path = rest[0] if rest else ""
        try:
            with open(path, errors="replace") as fh:
                kind = vpn_file_type(path, fh.read(200000))
        except OSError as exc:
            done(False, str(exc))
        if not kind:
            done(False, "not an OpenVPN (.ovpn) or WireGuard (.conf) file")
        ok, out, err = nmcli("connection", "import", "type", kind, "file", path, timeout=30)
        done(ok, (out.strip().splitlines() or ["imported"])[-1] if ok else err)
    elif cmd == "airplane":
        airplane(rest[0] if rest else "toggle")
    elif cmd == "hostname":
        if rest:
            hostname(rest[0])
        print(hostname())
    elif cmd == "bt":
        bt(rest)
    else:
        done(False, f"unknown command {cmd} (see network-settings.py with no arguments)")


if __name__ == "__main__":
    main(sys.argv[1:])
