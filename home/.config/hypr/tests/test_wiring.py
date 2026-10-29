"""Loose ends wired up: the window switcher follows switcher.conf, wol.py
reads `ip -j neigh` and the MACs peers.py notes at pairing, an upgrade
redraws the reboot pill, the on-screen keyboard has its key, the launcher's
Bluetooth command, and the Timers page's one work-hours row.

Hermetic: nothing is run against the screens, the network or systemd;
peers.json and wol.json are scratch files."""
import json
import os
import unittest

import helpers
import test_peers

SW = helpers.import_script("window-switcher.py", "window_switcher")
W = helpers.import_script("wol.py")
HYPR = os.path.dirname(helpers.SCRIPTS)

CLIENTS = [
    {"address": "0x1", "mapped": True, "focusHistoryID": 2, "monitor": 0,
     "workspace": {"id": 1, "name": "1"}, "class": "kitty", "title": "a"},
    {"address": "0x2", "mapped": True, "focusHistoryID": 0, "monitor": 1,
     "workspace": {"id": 4, "name": "4"}, "class": "firefox", "title": "b"},
    {"address": "0x3", "mapped": True, "focusHistoryID": 1, "monitor": 0,
     "workspace": {"id": -98, "name": "special:term"}, "class": "kitty", "title": "c"},
    {"address": "0x4", "mapped": False, "focusHistoryID": 3, "monitor": 0,
     "workspace": {"id": 1, "name": "1"}, "class": "x", "title": "hidden"},
]
DEFAULTS = {"scope": "all", "order": "recent", "special": "on", "lines": "15"}


def addrs(clients):
    return [c["address"] for c in clients]


class WindowSwitcher(unittest.TestCase):
    def test_defaults_are_the_old_behaviour(self):
        # every mapped window, most recently focused first
        self.assertEqual(addrs(SW.windows(CLIENTS, None, DEFAULTS)), ["0x2", "0x3", "0x1"])

    def test_scope_workspace_and_monitor(self):
        active = {"id": 1, "monitorID": 0}
        self.assertEqual(addrs(SW.windows(CLIENTS, active, dict(DEFAULTS, scope="workspace"))), ["0x1"])
        self.assertEqual(addrs(SW.windows(CLIENTS, active, dict(DEFAULTS, scope="monitor"))), ["0x3", "0x1"])

    def test_scope_without_an_answer_lists_everything(self):
        self.assertEqual(len(SW.windows(CLIENTS, None, dict(DEFAULTS, scope="workspace"))), 3)
        self.assertEqual(SW.focused({"id": "x"}), (None, None))

    def test_special_off_and_workspace_order(self):
        conf = dict(DEFAULTS, special="off", order="workspace")
        self.assertEqual(addrs(SW.windows(CLIENTS, None, conf)), ["0x1", "0x2"])

    def test_rows_and_picks(self):
        self.assertEqual(SW.wofi_argv(3, 10)[-1], "4")
        self.assertEqual(SW.wofi_argv(40, 20)[-1], "21")
        listed = SW.windows(CLIENTS, None, DEFAULTS)
        self.assertEqual(SW.picked("01    term  kitty  c", listed), "0x3")
        self.assertIsNone(SW.picked("typed words", listed))
        self.assertIsNone(SW.picked("99 x", listed))
        self.assertIsNone(SW.windows(None, None, DEFAULTS) or None)

    def test_page_says_it_is_read(self):
        import switcher_conf
        self.assertTrue(switcher_conf.wired())


class SwitcherPage(unittest.TestCase):
    def test_keys_text_follows_the_main_modifier(self):
        try:
            import gi
            gi.require_version("Gtk", "3.0")
            gi.require_version("Gdk", "3.0")
            from settings_pages import switcher as page
        except Exception as exc:                                    # noqa: BLE001
            raise unittest.SkipTest(f"settings_pages.switcher not importable: {exc}")
        self.assertIn("ALT+Tab", page.keys_text())
        self.assertIn("SUPER+U", page.keys_text("SUPER"))
        self.assertIn(page.main_mod(), ("ALT", "SUPER"))
        with open(page.__file__) as handle:
            self.assertNotIn("does not read these choices yet", handle.read())


NEIGH = json.dumps([
    {"dst": "192.168.1.20", "dev": "enp5s0", "lladdr": "AA:BB:CC:00:11:22", "state": ["STALE"]},
    {"dst": "192.168.1.30", "dev": "enp5s0", "state": ["FAILED"]},
    {"dst": "fe80::1:2", "dev": "enp5s0", "lladdr": "aa:bb:cc:00:11:33", "state": ["REACHABLE"]},
    {"dst": "192.168.1.40", "dev": "enp5s0", "lladdr": "aa:bb:cc:00:11:44", "state": ["INCOMPLETE"]},
])
ARP = """IP address       HW type     Flags       HW address            Mask     Device
192.168.1.50     0x1         0x2         aa:bb:cc:00:11:55     *        enp5s0
"""


class WolNeighbours(unittest.TestCase):
    def test_neigh_lookup(self):
        self.assertEqual(W.neigh_lookup(NEIGH, "192.168.1.20"), "aa:bb:cc:00:11:22")
        self.assertEqual(W.neigh_lookup(NEIGH, "::ffff:192.168.1.20"), "aa:bb:cc:00:11:22")
        self.assertEqual(W.neigh_lookup(NEIGH, "fe80:0::1:2"), "aa:bb:cc:00:11:33")       # IPv6, any spelling
        self.assertIsNone(W.neigh_lookup(NEIGH, "192.168.1.30"))                         # no lladdr
        self.assertIsNone(W.neigh_lookup(NEIGH, "192.168.1.40"))                         # incomplete
        self.assertIsNone(W.neigh_lookup("not json", "192.168.1.20"))

    def test_arp_is_the_fallback(self):
        self.assertEqual(W.lookup_mac("192.168.1.50", NEIGH, ARP), "aa:bb:cc:00:11:55")
        self.assertEqual(W.lookup_mac("::ffff:192.168.1.50", "", ARP), "aa:bb:cc:00:11:55")
        self.assertIsNone(W.lookup_mac("nas", "", ARP))

    def test_pairing_macs_fill_in(self):
        machines = {"nas": {"name": "nas", "mac": "aa:bb:cc:00:00:01"},
                    "Desk": {"name": "Desk", "mac": "aa:bb:cc:00:00:02", "peer": "p2"}}
        peers = [{"id": "p1", "name": "laptop", "mac": "aa:bb:cc:00:00:03"},
                 {"id": "p2", "name": "Desk", "mac": "aa:bb:cc:00:00:09"},      # wol.json wins
                 {"id": "p3", "name": "tower"},                                  # no MAC noted
                 {"id": "p4", "name": "NAS", "mac": "aa:bb:cc:00:00:04"}]        # name taken
        out = W.with_peers(machines, peers)
        self.assertEqual(out["laptop"], {"name": "laptop", "mac": "aa:bb:cc:00:00:03", "peer": "p1",
                                         "from": "pairing"})
        self.assertEqual(out["Desk"]["mac"], "aa:bb:cc:00:00:02")
        self.assertEqual(set(out), {"nas", "Desk", "laptop"})
        self.assertEqual(W.find(out, "p1")["name"], "laptop")
        self.assertEqual(machines.keys(), {"nas", "Desk"})                       # not changed

    def test_load_all_reads_peers_json(self):
        d = os.path.join(helpers.SCRATCH, "wiring-wol")
        os.makedirs(d, exist_ok=True)
        wol, peers = os.path.join(d, "wol.json"), os.path.join(d, "peers.json")
        with open(peers, "w") as handle:
            json.dump({"peers": [{"id": "p1", "name": "laptop", "mac": "aa:bb:cc:00:00:03"}]}, handle)
        self.assertEqual(list(W.load_all(wol, peers)), ["laptop"])
        self.assertEqual(W.load_all(wol, os.path.join(d, "none.json")), {})


class PeersKeepTheMac(unittest.TestCase):
    def test_tidy_peer_keeps_a_valid_mac(self):
        tidy = test_peers.peers.tidy_peer
        base = {"id": "a" * 64, "name": "laptop", "cert": "x"}
        self.assertEqual(tidy(dict(base, mac="aa:bb:cc:00:11:22"))["mac"], "aa:bb:cc:00:11:22")
        self.assertNotIn("mac", tidy(dict(base, mac="nonsense")))
        self.assertNotIn("mac", tidy(base))

    def test_repairing_without_a_lookup_keeps_the_mac(self):
        from unittest import mock
        P = test_peers.peers
        pem = P.identity()[0]
        with mock.patch.object(P, "neighbour_mac", return_value="aa:bb:cc:00:11:22"):
            fp = P.add_peer("laptop", pem, "127.0.0.1", 47000)
        with mock.patch.object(P, "neighbour_mac", return_value=None):
            P.add_peer("laptop", pem, "127.0.0.1", 47000)
        peer = next(p for p in P.load()["peers"] if p["id"] == fp)
        self.assertEqual(peer.get("mac"), "aa:bb:cc:00:11:22")
        P.update(lambda conf: conf.update(peers=[p for p in conf["peers"] if p["id"] != fp]))


class Wiring(unittest.TestCase):
    def read(self, *path):
        with open(os.path.join(*path)) as handle:
            return handle.read()

    def test_upgrade_pokes_the_reboot_pill_after_the_record(self):
        text = self.read(os.path.expanduser("~/.config/waybar/scripts/safe-upgrade.sh"))
        self.assertIn("bar_signals.py\" poke reboot", text)
        self.assertGreater(text.index("poke reboot"), text.index('mv -f "$record.tmp" "$record"'))

    def test_osk_key(self):
        text = self.read(HYPR, "lua", "binds.lua")
        self.assertIn('hl.bind("SUPER+CTRL+K", hl.dsp.exec_cmd("~/.config/hypr/scripts/osk.py toggle")', text)
        self.assertIn('description = "Accessibility: On-screen keyboard"', text)

    def test_launcher_bluetooth(self):
        launcher = helpers.import_script("launcher.py")
        rows = [c for c in launcher.COMMANDS if c[0] == "Bluetooth"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][3][1:3], ["toggle", "bluetooth"])
        self.assertFalse(hasattr(launcher, "bar_signals"))

    def test_timers_page_links_work_hours(self):
        text = self.read(helpers.SCRIPTS, "settings_pages", "timers.py")
        self.assertIn('link("Open Work hours", lambda: spawn(SETTINGS, "workhours"))', text)
        self.assertNotIn("toggle_day", text)


if __name__ == "__main__":
    unittest.main()
