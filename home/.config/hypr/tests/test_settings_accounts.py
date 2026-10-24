"""accounts.py (Settings > Users, sharing & printers) and the page's pure
helpers: the parsers for the login screen's config, firewalld, lsblk, ABRT
and lpstat; the root commands (the greetd ones are run, without sudo, on a
scratch copy); the picture change and its undo with AccountsService stubbed
and ~/.face pointed at a scratch file. Nothing reaches the system: no D-Bus
call, no sudo, no clipboard."""
import os
import subprocess
import tempfile
import unittest
from unittest import mock

import helpers

try:
    import gi
    gi.require_version("Gtk", "3.0")       # the page needs GTK 3; pin it before anything loads GTK 4
except (ImportError, ValueError):
    pass

acc = helpers.import_script("accounts.py")

GREETD = """\
[terminal]
vt = "1"

[general]
service = "cosmic-greeter"

[default_session]
command = "cosmic-greeter-start"
user = "cosmic-greeter"
"""

LIST_ALL = """\
FedoraWorkstation (default, active)
  target: default
  interfaces: enp7s0
  sources:
  services: dhcpv6-client mdns samba-client ssh
  ports: 1025-65535/udp 1025-65535/tcp
  protocols:
"""

LPSTAT = """\
printer L396-Series disabled since Fri Jul 10 19:14:16 2026 -
\tUnplugged or turned off
\tForm mounted:
\tDescription: Epson L396
\tLocation: Office
printer Laser is idle.  enabled since Mon Oct 19 10:00:00 2026
\tForm mounted:
\tDescription: Laser
printer Big now printing Big-7.  enabled since Mon Oct 19 10:00:00 2026
\tForm mounted:
"""


class LoginScreen(unittest.TestCase):
    def test_greetd_without_initial_session(self):
        self.assertIsNone(acc.greetd_autologin(GREETD))

    def test_greetd_with_initial_session(self):
        text = GREETD + '\n[initial_session]\ncommand = "/usr/bin/start-hyprland"\nuser = "me"  # me\n'
        self.assertEqual(acc.greetd_autologin(text), "me")

    def test_greetd_needs_a_command(self):
        self.assertIsNone(acc.greetd_autologin(GREETD + '[initial_session]\nuser = "me"\n'))

    def test_gdm(self):
        on = "[daemon]\nAutomaticLoginEnable=True\nAutomaticLogin=me\n"
        off = "[daemon]\nAutomaticLoginEnable=False\nAutomaticLogin=me\n"
        self.assertEqual(acc.ini_autologin(on, "gdm"), "me")
        self.assertIsNone(acc.ini_autologin(off, "gdm"))
        self.assertIsNone(acc.ini_autologin("[daemon]\n#AutomaticLogin=me\n", "gdm"))

    def test_sddm_and_lightdm(self):
        self.assertEqual(acc.ini_autologin("[Autologin]\nUser=me\n", "sddm"), "me")
        self.assertEqual(acc.ini_autologin("[Seat:*]\nautologin-user=me\n", "lightdm"), "me")
        self.assertIsNone(acc.ini_autologin("[Seat:*]\n#autologin-user=me\n", "lightdm"))


class RootCommands(unittest.TestCase):
    def run_without_sudo(self, cmd):
        subprocess.run(["bash", "-c", cmd.replace("sudo ", "")], check=True)

    def test_greetd_on_then_off_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            conf = os.path.join(tmp, "greeter.toml")
            with open(conf, "w") as f:
                f.write(GREETD)
            on = acc.root_command("autologin-on", login="me", config=conf, kind="greetd")
            self.assertTrue(on.startswith("sudo "))
            self.run_without_sudo(on)
            self.run_without_sudo(on)                   # twice: still one section
            text = open(conf).read()
            self.assertEqual(text.count("[initial_session]"), 1)
            self.assertEqual(acc.greetd_autologin(text), "me")
            self.assertIn('user = "cosmic-greeter"', text)  # the greeter's own section is kept
            self.assertTrue(os.path.exists(conf + ".orig"))
            self.run_without_sudo(acc.root_command("autologin-off", login="me", config=conf, kind="greetd"))
            text = open(conf).read()
            self.assertIsNone(acc.greetd_autologin(text))
            self.assertEqual(text.strip(), GREETD.strip())

    def test_off_keeps_a_later_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            conf = os.path.join(tmp, "g.toml")
            with open(conf, "w") as f:
                f.write('[initial_session]\ncommand = "x"\nuser = "me"\n\n[default_session]\ncommand = "y"\n')
            self.run_without_sudo(acc.root_command("autologin-off", config=conf, kind="greetd"))
            self.assertEqual(open(conf).read().strip(), '[default_session]\ncommand = "y"')

    def test_firewall_and_ssh(self):
        self.assertEqual(acc.root_command("firewall-open", "kdeconnect"),
                         "sudo firewall-cmd --permanent --add-service=kdeconnect && sudo firewall-cmd --reload")
        self.assertEqual(acc.root_command("firewall-zone", "home"), "sudo firewall-cmd --set-default-zone=home")
        self.assertIn("disable --now sshd", acc.root_command("ssh-off"))

    def test_rejects_odd_names_and_unknown_steps(self):
        for bad in ("ssh; rm -rf ~", "$(id)", "a b", ""):
            with self.assertRaises(ValueError):
                acc.root_command("firewall-open", bad)
        with self.assertRaises(ValueError):
            acc.root_command("reboot")
        with self.assertRaises(ValueError):
            acc.root_command("autologin-on", login="me", config="/x", kind=None)

    def test_password_is_never_run_here(self):
        argv = acc.password_argv()
        self.assertEqual(argv[1:4], ["run", "terminal", "--"])
        self.assertIn("passwd", argv[-1])


class Parsers(unittest.TestCase):
    def test_firewall_list_all(self):
        info = acc.parse_list_all(LIST_ALL)
        self.assertEqual(info["zone"], "FedoraWorkstation")
        self.assertEqual(info["services"], ["dhcpv6-client", "mdns", "samba-client", "ssh"])
        self.assertEqual(info["interfaces"], ["enp7s0"])
        self.assertEqual(len(info["ports"]), 2)
        self.assertEqual(acc.parse_list_all("")["services"], [])

    def test_encryption(self):
        tree = {"blockdevices": [
            {"name": "nvme0n1", "type": "disk", "children": [
                {"name": "p1", "type": "part", "fstype": "vfat", "mountpoints": ["/boot/efi"]},
                {"name": "p3", "type": "part", "fstype": "crypto_LUKS", "mountpoints": [None], "children": [
                    {"name": "luks-1", "type": "crypt", "fstype": "btrfs", "mountpoints": ["/home", "/"]}]}]},
            {"name": "sda", "type": "disk", "fstype": None, "children": [
                {"name": "sda1", "type": "part", "fstype": "ext4", "mountpoints": ["/mnt/data"]}]},
            {"name": "zram0", "type": "disk", "mountpoints": ["[SWAP]"]}]}
        self.assertEqual(acc.encryption(tree), [{"mount": "/", "encrypted": True},
                                                {"mount": "/home", "encrypted": True},
                                                {"mount": "/mnt/data", "encrypted": False}])
        self.assertEqual(acc.encryption({}), [])

    def test_abrt_count(self):
        self.assertEqual(acc.parse_problem_count("ABRT has detected 55 problems. For more"), 55)
        self.assertEqual(acc.parse_problem_count("ABRT has detected 1 problem(s)."), 1)
        self.assertEqual(acc.parse_problem_count(""), 0)

    def test_printers(self):
        ps = acc.parse_printers(LPSTAT)
        self.assertEqual([p["name"] for p in ps], ["L396-Series", "Laser", "Big"])
        self.assertEqual(ps[0]["state"], "disabled")
        self.assertEqual(ps[0]["reason"], "Unplugged or turned off")
        self.assertEqual(ps[0]["since"], "Fri Jul 10 19:14:16 2026")
        self.assertEqual((ps[0]["description"], ps[0]["location"]), ("Epson L396", "Office"))
        self.assertEqual(ps[1]["state"], "idle")
        self.assertIsNone(ps[1]["reason"])
        self.assertEqual(ps[2]["state"], "printing")

    def test_jobs(self):
        jobs = acc.parse_jobs("Laser-12   me   2048   Tue 20 Oct 2026 04:00:00 AM CST\n")
        self.assertEqual(jobs, [{"id": "Laser-12", "printer": "Laser", "user": "me", "size": 2048,
                                 "when": "Tue 20 Oct 2026 04:00:00 AM CST"}])
        self.assertEqual(acc.parse_jobs(""), [])


class Picture(unittest.TestCase):
    def setUp(self):
        try:
            import gi
            gi.require_version("GdkPixbuf", "2.0")
            from gi.repository import GdkPixbuf
        except (ImportError, ValueError) as exc:
            raise unittest.SkipTest(f"GdkPixbuf missing: {exc}")
        self.GdkPixbuf = GdkPixbuf
        self.tmp = tempfile.mkdtemp(dir=helpers.SCRATCH)
        self.face = os.path.join(self.tmp, ".face")
        self.icon = os.path.join(self.tmp, "accounts-icon")
        self.source = os.path.join(self.tmp, "wide.png")
        pix = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 400, 200)
        pix.fill(0x3366ccff)
        pix.savev(self.source, "png", [], [])
        with open(self.icon, "wb") as f:
            f.write(b"old login-screen picture")
        self.calls = []
        patches = [mock.patch.object(acc, "FACE", self.face),
                   mock.patch.object(acc, "STATE", os.path.join(self.tmp, "state")),
                   mock.patch.object(acc, "accounts_user", lambda uid: {"IconFile": self.icon, "_path": "/u"}),
                   mock.patch.object(acc, "call_user", lambda *a: self.calls.append(a) or "")]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_square_crop(self):
        out = os.path.join(self.tmp, "sq.png")
        acc.square_png(self.source, out, 64)
        pix = self.GdkPixbuf.Pixbuf.new_from_file(out)
        self.assertEqual((pix.get_width(), pix.get_height()), (64, 64))

    def test_not_a_picture(self):
        bad = os.path.join(self.tmp, "x.png")
        with open(bad, "w") as f:
            f.write("text")
        with self.assertRaises(ValueError):
            acc.square_png(bad, os.path.join(self.tmp, "o.png"))

    def test_set_then_undo(self):
        msg = acc.set_avatar(self.source)
        self.assertIn("picture set", msg)
        self.assertTrue(os.path.exists(self.face))
        self.assertEqual(self.calls[-1], ("SetIconFile", "(s)", self.face))
        kept = os.path.join(acc.STATE, "previous-icon")
        self.assertEqual(open(kept, "rb").read(), b"old login-screen picture")
        ok, _ = acc.undo_avatar()
        self.assertTrue(ok)
        self.assertFalse(os.path.exists(self.face))              # there was none before
        self.assertEqual(self.calls[-1], ("SetIconFile", "(s)", kept))
        self.assertFalse(acc.undo_avatar()[0])                   # nothing left to undo

    def test_undo_restores_an_earlier_face(self):
        with open(self.face, "wb") as f:
            f.write(b"my old face")
        acc.set_avatar(self.source)
        acc.undo_avatar()
        self.assertEqual(open(self.face, "rb").read(), b"my old face")


    def test_two_changes_keep_the_original(self):
        with open(self.face, "wb") as f:
            f.write(b"my old face")
        acc.set_avatar(self.source)
        acc.set_avatar(self.source)                              # a second try must not lose the first
        self.assertTrue(acc.undo_avatar()[0])
        self.assertEqual(open(self.face, "rb").read(), b"my old face")

    def test_a_linked_face_leaves_the_photo_alone(self):
        photo = os.path.join(self.tmp, "photo.jpg")
        with open(photo, "wb") as f:
            f.write(b"a photo")
        os.symlink(photo, self.face)
        acc.set_avatar(self.source)
        self.assertEqual(open(photo, "rb").read(), b"a photo")   # the link was replaced, not written through
        self.assertFalse(os.path.islink(self.face))

    def test_failed_undo_can_be_tried_again(self):
        acc.set_avatar(self.source)
        with mock.patch.object(acc, "call_user", lambda *a: "denied"):
            self.assertFalse(acc.undo_avatar()[0])
        self.assertTrue(acc.undo_avatar()[0])


class PageText(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import gi
            gi.require_version("Gtk", "3.0")
            gi.require_version("Gdk", "3.0")
            from settings_pages import accounts as page
        except Exception as exc:                                     # no GTK here
            raise unittest.SkipTest(f"settings_pages.accounts not importable: {exc}")
        cls.page = page

    def test_autologin(self):
        lg = {"dm": "cosmic-greeter", "kind": "greetd", "config": "/etc/g.toml", "readable": True,
              "autologin": None, "mine": False}
        self.assertTrue(self.page.autologin_sub(lg).startswith("off"))
        self.assertTrue(self.page.autologin_sub(dict(lg, autologin="me", mine=True)).startswith("ON"))
        self.assertIn("not readable", self.page.autologin_sub(dict(lg, readable=False)))

    def test_disks(self):
        self.assertIn("every disk", self.page.disks_sub([{"mount": "/", "encrypted": True}]))
        self.assertIn("not encrypted: /home", self.page.disks_sub([{"mount": "/", "encrypted": True},
                                                                   {"mount": "/home", "encrypted": False}]))

    def test_printer(self):
        p = {"name": "P", "state": "disabled", "since": "Fri", "reason": "Unplugged", "connection": "usb",
             "location": ""}
        text = self.page.printer_sub(p, "P")
        self.assertTrue(text.startswith("PAUSED since Fri"))
        self.assertIn("default", text)
        self.assertEqual(self.page.printer_sub(dict(p, state="idle", reason=None), None), "ready  ·  USB")

    def test_kdeconnect_and_ssh_follow_the_firewall(self):
        ws = {"running": True, "services": ["ssh"], "ports": ["1025-65535/udp", "1025-65535/tcp"]}
        self.assertIn("lets it in", self.page.phone_sub([], True, ws))
        self.assertIn("shuts it out", self.page.phone_sub([], True, dict(ws, ports=[])))
        self.assertIn("lets it in", self.page.phone_sub([], True, {"running": False}))
        ssh = {"installed": True, "active": True, "enabled": True}
        self.assertIn("no firewall", self.page.ssh_sub(ssh, {"running": False}))
        self.assertIn("does not let it in", self.page.ssh_sub(ssh, dict(ws, services=[])))

    def test_firewall(self):
        self.assertIn("NOT running", self.page.firewall_sub({"installed": True, "running": False}))
        self.assertIn("not installed", self.page.firewall_sub({"installed": False}))


if __name__ == "__main__":
    unittest.main()
