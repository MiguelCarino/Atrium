"""wol.py: the magic packet, MAC spellings, the neighbour-table lookup, the
saved machines, and send() against a fake socket -- no packet leaves."""
import os
import shutil
import tempfile
import unittest

import helpers

W = helpers.import_script("wol.py")
ARP = """IP address       HW type     Flags       HW address            Mask     Device
192.168.1.20     0x1         0x2         aa:bb:cc:00:11:22     *        enp5s0
192.168.1.30     0x1         0x0         00:00:00:00:00:00     *        enp5s0
"""


class FakeSock:
    def __init__(self):
        self.sent, self.opts, self.closed = [], [], False

    def setsockopt(self, *args):
        self.opts.append(args)

    def sendto(self, data, addr):
        self.sent.append((data, addr))
        return len(data)

    def close(self):
        self.closed = True


class Packet(unittest.TestCase):
    def test_spellings(self):
        want = bytes.fromhex("aabbcc001122")
        for text in ("aa:bb:cc:00:11:22", "AA-BB-CC-00-11-22", "aabb.cc00.1122", "aabbcc001122", " aa bb cc 00 11 22 "):
            self.assertEqual(W.parse_mac(text), want, text)

    def test_bad_macs(self):
        for text in ("", "aa:bb:cc", "zz:bb:cc:00:11:22", "00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff", None):
            with self.assertRaises(ValueError):
                W.parse_mac(text)

    def test_magic_packet(self):
        packet = W.magic_packet("aa:bb:cc:00:11:22")
        self.assertEqual(len(packet), 102)
        self.assertEqual(packet[:6], b"\xff" * 6)
        self.assertEqual(packet[6:], bytes.fromhex("aabbcc001122") * 16)

    def test_send_broadcasts(self):
        sock = FakeSock()
        n = W.send("aa:bb:cc:00:11:22", "192.168.1.255", 7, sock_factory=lambda: sock)
        self.assertEqual(n, 3 * 102)
        self.assertEqual(sock.sent[0][1], ("192.168.1.255", 7))
        self.assertIn((W.socket.SOL_SOCKET, W.socket.SO_BROADCAST, 1), sock.opts)
        self.assertTrue(sock.closed)

    def test_check_ip(self):
        self.assertEqual(W.check_ip("10.0.0.255"), "10.0.0.255")
        for bad in ("10.0.0", "nas", "1.2.3.4.5"):
            with self.assertRaises(ValueError):
                W.check_ip(bad)


class Machines(unittest.TestCase):
    def test_arp_lookup(self):
        self.assertEqual(W.arp_lookup(ARP, "192.168.1.20"), "aa:bb:cc:00:11:22")
        self.assertIsNone(W.arp_lookup(ARP, "192.168.1.30"))       # incomplete
        self.assertIsNone(W.arp_lookup(ARP, "192.168.1.99"))
        self.assertIsNone(W.arp_lookup("", "1.2.3.4"))

    def test_add_find_and_peer(self):
        m = W.add({}, "Desk", "AA-BB-CC-00-11-22", peer="P1")
        m = W.add(m, "Laptop", "aabbcc001133", broadcast="192.168.1.255")
        self.assertEqual(W.find(m, "desk")["mac"], "aa:bb:cc:00:11:22")
        self.assertEqual(W.find(m, "P1")["name"], "Desk")
        self.assertEqual(W.find(m, "aa:bb:cc:00:11:33")["name"], "Laptop")
        self.assertIsNone(W.find(m, "nobody"))
        self.assertEqual(W.for_peer(m, "P1")["name"], "Desk")
        self.assertEqual(W.for_peer(m, "P9", "laptop")["name"], "Laptop")
        self.assertIsNone(W.for_peer(m, "P9"))

    def test_add_replaces_same_name_or_peer(self):
        m = W.add({}, "Desk", "aabbcc001122", peer="P1")
        m = W.add(m, "Desk (new)", "aabbcc001144", peer="P1")
        self.assertEqual(list(m), ["Desk (new)"])
        with self.assertRaises(ValueError):
            W.add(m, "", "aabbcc001122")
        with self.assertRaises(ValueError):
            W.add(m, "x", "aabbcc001122", broadcast="nope")

    def test_options(self):
        self.assertEqual(W.options(["Desk", "--peer", "P1", "aa"], ("--peer",)), (["Desk", "aa"], {"peer": "P1"}))

    def test_save_load(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder)
        path = os.path.join(folder, "wol.json")
        self.assertEqual(W.load(path), {})
        W.save(W.add({}, "Desk", "aabbcc001122"), path)
        self.assertEqual(W.load(path)["Desk"]["mac"], "aa:bb:cc:00:11:22")


if __name__ == "__main__":
    unittest.main()
