"""network-settings.py (the Network & Bluetooth page's backend) and the
page's own text helpers: parsing nmcli / rfkill / BlueZ output, the Wi-Fi
connection settings, hostname and VPN-file checks, and airplane mode's
remember-and-restore -- with every command stubbed, so no radio, connection
or file outside the scratch folder is touched."""
import contextlib
import io
import json
import os
import unittest

import helpers

net = helpers.import_script("network-settings.py", "network_settings")


class Nmcli(unittest.TestCase):
    def test_split_terse(self):
        self.assertEqual(net.split_terse(r"*:Cafe\:Guest:AA\:BB\:CC\:DD\:EE\:FF:70"),
                         ["*", "Cafe:Guest", "AA:BB:CC:DD:EE:FF", "70"])
        self.assertEqual(net.split_terse(r"a\\b:c"), ["a\\b", "c"])

    def test_multiline(self):
        text = ("GENERAL.DEVICE:enp7s0\nGENERAL.STATE:100 (connected)\nIP4.ADDRESS[1]:10.0.0.5/24\n"
                "IP4.ADDRESS[2]:10.0.0.6/24\nIP6.ADDRESS[1]:fe80::1/64\nIP4.GATEWAY:\nnonsense\n")
        d = net.parse_multiline(text)
        self.assertEqual(d["IP4.ADDRESS"], ["10.0.0.5/24", "10.0.0.6/24"])
        self.assertEqual(d["IP6.ADDRESS"], ["fe80::1/64"])            # IPv6 colons are not escaped here
        self.assertEqual(d["IP4.GATEWAY"], "")
        self.assertEqual(d["GENERAL.STATE"], "100 (connected)")

    def test_security_kind(self):
        for sec, kind in (("", "open"), ("--", "open"), ("WPA2", "psk"), ("WPA1 WPA2", "psk"), ("WPA3", "psk"),
                          ("WPA2 802.1X", "enterprise"), ("WEP", "wep"), ("OWE", "owe")):
            self.assertEqual(net.security_kind(sec), kind, sec)

    def test_bars(self):
        self.assertEqual(net.bars(100), "▂▄▆█")
        self.assertEqual(net.bars(60), "▂▄▆_")
        self.assertEqual(net.bars(30), "▂▄__")
        self.assertEqual(net.bars(10), "▂___")
        self.assertEqual(net.bars(0), "____")

    def test_wifi_list(self):
        text = "\n".join([
            r" :Home:AA\:00\:00\:00\:00\:01:40:WPA2:6:130 Mbit/s",
            r" :Home:AA\:00\:00\:00\:00\:02:80:WPA2:36:540 Mbit/s",      # same name, stronger: wins
            r"*:Cafe\:Guest:AA\:00\:00\:00\:00\:03:30::11:54 Mbit/s",     # in use: first, even though weaker
            r" :Cafe\:Guest:AA\:00\:00\:00\:00\:04:90::1:54 Mbit/s",      # stronger, but not the one in use
            r" ::AA\:00\:00\:00\:00\:05:99:WPA2:1:54 Mbit/s",             # hidden: left out
            r" :Uni:AA\:00\:00\:00\:00\:06:50:WPA2 802.1X:1:54 Mbit/s",
            "garbage"])
        nets = net.parse_wifi_list(text, {"Home": "uuid-home"})
        self.assertEqual([n["ssid"] for n in nets], ["Cafe:Guest", "Home", "Uni"])
        cafe, home, uni = nets
        self.assertTrue(cafe["in_use"])
        self.assertEqual((cafe["signal"], cafe["kind"], cafe["band"]), (30, "open", "2.4 GHz"))
        self.assertEqual((home["signal"], home["band"], home["saved"]), (80, "5 GHz", "uuid-home"))
        self.assertIsNone(uni["saved"])
        self.assertEqual(uni["kind"], "enterprise")


class Checks(unittest.TestCase):
    def test_airplane_rule(self):
        self.assertFalse(net.rfkill_airplane([]))
        self.assertTrue(net.rfkill_airplane([{"soft": "blocked"}, {"soft": "blocked"}]))
        self.assertFalse(net.rfkill_airplane([{"soft": "blocked"}, {"soft": "unblocked"}]))

    def test_hostname(self):
        for good in ("desktop", "my-pc", "a", "pc1.lan", "x" * 63):
            self.assertTrue(net.valid_hostname(good), good)
        for bad in ("", "my pc", "-pc", "pc-", "pc..lan", "x" * 64, "ñandú", "a_b", "x" * 30 + "." + "y" * 34):
            self.assertFalse(net.valid_hostname(bad), bad)

    def test_vpn_file(self):
        self.assertEqual(net.vpn_file_type("x.conf", "[Interface]\nPrivateKey = abc\n[Peer]\n"), "wireguard")
        self.assertEqual(net.vpn_file_type("x.ovpn", "anything"), "openvpn")
        self.assertEqual(net.vpn_file_type("x.conf", "client\ndev tun\nremote vpn.example 1194\n"), "openvpn")
        self.assertIsNone(net.vpn_file_type("x.conf", "hello"))

    def test_wifi_settings(self):
        s = net.wifi_settings("Cafe", "secret123")
        self.assertEqual(s["802-11-wireless"]["ssid"], b"Cafe")
        self.assertEqual(s["802-11-wireless-security"], {"psk": "secret123"})   # NM fills key-mgmt from the AP
        self.assertNotIn("hidden", s["802-11-wireless"])
        h = net.wifi_settings("Secret", "secret123", hidden=True)
        self.assertTrue(h["802-11-wireless"]["hidden"])
        self.assertEqual(h["802-11-wireless-security"]["key-mgmt"], "wpa-psk")
        self.assertNotIn("802-11-wireless-security", net.wifi_settings("Open"))


class Bluez(unittest.TestCase):
    def test_devices(self):
        objects = {
            "/org/bluez/hci0": {"org.bluez.Adapter1": {"Powered": True, "Alias": "pc"}},
            "/org/bluez/hci0/dev_1": {"org.bluez.Device1": {"Address": "00:00:00:00:00:01", "Alias": "Mouse",
                                                            "Name": "Mouse", "Paired": True, "Icon": "input-mouse"}},
            "/org/bluez/hci0/dev_2": {"org.bluez.Device1": {"Address": "00:00:00:00:00:02", "Alias": "Buds",
                                                            "Name": "Buds", "Paired": True, "Connected": True},
                                      "org.bluez.Battery1": {"Percentage": 64}},
            "/org/bluez/hci0/dev_3": {"org.bluez.Device1": {"Address": "00:00:00:00:00:03",
                                                            "Alias": "00-00-00-00-00-03", "RSSI": -40}},
            "/org/bluez/hci0/dev_4": {"org.bluez.Device1": {"Address": "00:00:00:00:00:04", "Alias": "Far",
                                                            "Name": "Far", "RSSI": -90}},
            "/org/bluez/hci0/dev_5": {"org.bluez.Device1": {"Address": "00:00:00:00:00:05", "Alias": "Near",
                                                            "Name": "Near", "RSSI": -50}},
        }
        adapter, devices = net.bt_devices(objects)
        self.assertTrue(adapter["Powered"])
        self.assertEqual([d["name"] for d in devices], ["Buds", "Mouse", "Near", "Far"])   # nameless one left out
        self.assertEqual(devices[0]["battery"], 64)
        self.assertIsNone(devices[1]["battery"])
        self.assertTrue(devices[0]["connected"])


class Pair(unittest.TestCase):
    """bt pair when BlueZ has already dropped the device a scan found (it does
    so 30 s after the scan): look again first, then pair -- or say why not.
    bluetoothctl and BlueZ's object list are stubbed."""

    MAC = "AA:BB:CC:DD:EE:FF"

    def setUp(self):
        self.calls, self.known_after_scans = [], 1
        saved = {k: getattr(net, k) for k in ("btctl", "bt_objects")}
        self.addCleanup(lambda: [setattr(net, k, v) for k, v in saved.items()])

        def btctl(*args, timeout=15):
            self.calls.append(args)
            return True, "", ""
        net.btctl = btctl
        net.bt_objects = lambda: ({"/org/bluez/hci0/dev": {"org.bluez.Device1": {"Address": self.MAC.lower()}}}
                                  if sum("scan" in c for c in self.calls) >= self.known_after_scans else {})

    def pair(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as ex:
            net.bt(["pair", self.MAC])
        return ex.exception.code, out.getvalue().strip(), err.getvalue().strip()

    def test_known_device_pairs_without_scanning(self):
        self.known_after_scans = 0
        self.assertEqual(self.pair()[0], 0)
        self.assertFalse(any("scan" in c for c in self.calls))
        self.assertTrue(any("pair" in c for c in self.calls))

    def test_forgotten_device_is_found_again_then_paired(self):
        code, out, _ = self.pair()
        self.assertEqual((code, out), (0, "paired and connected"))
        verbs = [c[-2] if c[-1] == self.MAC else c[-1] for c in self.calls]
        self.assertLess(verbs.index("on"), verbs.index("pair"))      # the scan came before the pairing

    def test_device_gone_says_so(self):
        self.known_after_scans = 99
        code, _, err = self.pair()
        self.assertEqual(code, 1)
        self.assertIn("pairing mode", err)
        self.assertFalse(any("pair" in c for c in self.calls))


class Airplane(unittest.TestCase):
    """Remember which radios were on, block everything; off puts them back."""

    def setUp(self):
        self.calls = []
        self.saved = {n: getattr(net, n) for n in ("sh", "nmcli", "rfkill", "bt_powered")}
        net.sh = lambda *cmd, **kw: (self.calls.append(cmd), (True, "", ""))[1]
        net.nmcli = lambda *a, **kw: (self.calls.append(("nmcli",) + a),
                                      (True, "enabled\n" if a == ("radio", "wifi") else "", ""))[1]
        net.bt_powered = lambda: False
        self.sleep, net.time.sleep = net.time.sleep, (lambda s: None)
        self.quiet = contextlib.ExitStack()
        self.quiet.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.quiet.enter_context(contextlib.redirect_stderr(io.StringIO()))
        try:
            os.remove(net.AIRPLANE_STATE)
        except OSError:
            pass

    def tearDown(self):
        self.quiet.close()
        net.time.sleep = self.sleep
        for n, f in self.saved.items():
            setattr(net, n, f)

    def test_on_then_off(self):
        self.assertTrue(net.AIRPLANE_STATE.startswith(helpers.SCRATCH))
        net.rfkill = lambda: [{"type": "wlan", "soft": "unblocked"}, {"type": "bluetooth", "soft": "blocked"}]
        with self.assertRaises(SystemExit) as ex:
            net.airplane("on")
        self.assertEqual(ex.exception.code, 0)
        self.assertIn(("rfkill", "block", "all"), self.calls)
        with open(net.AIRPLANE_STATE) as fh:
            self.assertEqual(json.load(fh), {"wifi": True, "bluetooth": False})

        self.calls.clear()
        net.rfkill = lambda: [{"type": "wlan", "soft": "blocked"}, {"type": "bluetooth", "soft": "blocked"}]
        with self.assertRaises(SystemExit):
            net.airplane("toggle")                                   # on -> off
        self.assertIn(("rfkill", "unblock", "all"), self.calls)
        self.assertIn(("nmcli", "radio", "wifi", "on"), self.calls)
        self.assertIn(("rfkill", "block", "bluetooth"), self.calls)  # it was off before: stays off
        self.assertNotIn(("bluetoothctl", "power", "on"), self.calls)
        self.assertFalse(os.path.exists(net.AIRPLANE_STATE))

    def test_off_without_memory_turns_both_on(self):
        net.rfkill = lambda: [{"type": "wlan", "soft": "blocked"}]
        with self.assertRaises(SystemExit):
            net.airplane("off")
        self.assertIn(("nmcli", "radio", "wifi", "on"), self.calls)
        self.assertIn(("bluetoothctl", "power", "on"), self.calls)


try:
    from settings_pages import network as page                      # needs GTK, not a display
except Exception:                                                   # noqa: BLE001
    page = None


@unittest.skipIf(page is None, "GTK not importable")
class PageText(unittest.TestCase):
    def test_wifi_sub(self):
        n = {"bars": "▂▄▆_", "signal": 70, "kind": "psk", "security": "WPA2", "band": "5 GHz",
             "in_use": False, "saved": "u"}
        self.assertEqual(page.wifi_sub(n), "▂▄▆_ 70%  ·  WPA2  ·  5 GHz  ·  saved")
        self.assertTrue(page.wifi_sub(dict(n, in_use=True)).startswith("connected  ·  "))
        self.assertIn("connection editor", page.wifi_sub(dict(n, kind="enterprise")))

    def test_bt_sub(self):
        self.assertEqual(page.bt_sub({"paired": True, "connected": True, "battery": 80}), "connected  ·  battery 80%")
        self.assertEqual(page.bt_sub({"paired": False, "rssi": -60, "battery": None}), "not paired  ·  signal -60 dBm")


if __name__ == "__main__":
    unittest.main()
