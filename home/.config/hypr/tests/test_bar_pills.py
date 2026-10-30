"""The bar's newer pills and panels, pure parts only: no window is opened,
no D-Bus or nmcli is reached, nothing is rebooted.

  panelui.py          label(), the two-click Arming rule, the keyboard walk
                      (first_match, arrow_move)
  memory_pill.py      memory-pressure pill: levels, top processes, text
  bluetooth.py        BlueZ objects -> summary -> pill; "Pair new..." pick
  bluetooth_panel.py  a device row's subtitle, D-Bus error text
  reboot_needed.py    kernel versions, needs-restarting's answer, the
                      reasons updates.sh reads
  reboot_panel.py     the card's lines; updates.sh's restart badge (stubbed
                      dnf / flatpak / reboot check); no custom/reboot left
  awake_pill.py       when to ask idle-settings.py, the pill
  network.py          VPNs in the pill; network_panel.py's VPN section
  notifications.py    the bell's tooltip (no click hints), the DND flag
  display_panel.py    "Remember this layout": which screens get written
  doctor.py, workspace-tint.py, style.css, panel.py: the phase-1 followups
"""
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest

import helpers

WAYBAR = os.path.join(os.path.dirname(os.path.dirname(helpers.SCRIPTS)), "waybar")
WAYBAR_SCRIPTS = os.path.join(WAYBAR, "scripts")
if WAYBAR_SCRIPTS not in sys.path:
    sys.path.insert(0, WAYBAR_SCRIPTS)


def load(name):
    spec = importlib.util.spec_from_file_location(f"{name.replace('-', '_')}_pills",
                                                  os.path.join(WAYBAR_SCRIPTS, f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    argv, sys.argv = sys.argv, [f"{name}.py"]
    try:
        spec.loader.exec_module(module)
    finally:
        sys.argv = argv
    return module


panelui = load("panelui")
mem = load("memory_pill")
bt = load("bluetooth")
btp = load("bluetooth_panel")
rb = load("reboot_needed")
rbp = load("reboot_panel")
aw = load("awake_pill")
net = load("network")
netp = load("network_panel")
notif = load("notifications")
disp = load("display_panel")
tint = load("workspace-tint")
panel = load("panel")
doctor = helpers.import_script("doctor.py")
theme = helpers.import_script("theme.py", "theme")
barfit = load("barfit")


class PanelUiTest(unittest.TestCase):
    def test_label(self):
        lab = panelui.label("Hi", "ctl-sub", 1.0)
        self.assertEqual(lab.get_text(), "Hi")
        self.assertTrue(lab.get_style_context().has_class("ctl-sub"))
        self.assertEqual(lab.get_xalign(), 1.0)
        self.assertEqual(panelui.label("x").get_xalign(), 0.0)

    def test_arming_needs_two_presses_in_time(self):
        arm = panelui.Arming(3)
        self.assertEqual(arm.press(100.0), "armed")
        self.assertTrue(arm.armed(101.0))
        self.assertEqual(arm.press(102.0), "fire")
        self.assertFalse(arm.armed(102.5))          # fired: back to rest
        self.assertEqual(arm.press(110.0), "armed")
        self.assertEqual(arm.press(113.5), "armed")   # too late: arms again
        arm.disarm()
        self.assertFalse(arm.armed(113.6))

    def test_a_held_key_is_not_a_second_press(self):
        arm = panelui.Arming(3)
        self.assertEqual(arm.press(100.0, by_key=True), "armed")
        self.assertEqual(arm.press(100.6, by_key=True), "held")    # Enter's auto-repeat
        self.assertTrue(arm.armed(100.7))
        arm.release()
        self.assertEqual(arm.press(101.0, by_key=True), "fire")
        # Armed by the keyboard, confirmed with the mouse: a real second press.
        self.assertEqual(arm.press(110.0, by_key=True), "armed")
        self.assertEqual(arm.press(110.5), "fire")

    def test_armed_button_fires_on_second_click(self):
        fired = []
        button = panelui.Armed("Forget", lambda: fired.append(1))
        button.clicked()
        self.assertEqual(button.get_label(), panelui.SURE)
        self.assertTrue(button.get_style_context().has_class("armed"))
        self.assertEqual(fired, [])
        button.clicked()
        self.assertEqual(fired, [1])
        self.assertEqual(button.get_label(), "Forget")
        self.assertFalse(button.get_style_context().has_class("armed"))
        button.clicked()
        button.disarm()
        self.assertEqual(button.get_label(), "Forget")

    def test_first_match_is_depth_first_in_order(self):
        tree = {"card": ["head", "body"], "head": ["title", "link"], "body": ["row1"],
                "row1": ["switch"]}
        kids = lambda n: tree.get(n, [])      # noqa: E731
        self.assertEqual(panelui.first_match("card", kids, lambda n: n in ("link", "switch")), "link")
        self.assertEqual(panelui.first_match("card", kids, lambda n: n == "switch"), "switch")
        self.assertIsNone(panelui.first_match("card", kids, lambda n: False))

    def test_arrow_move(self):
        self.assertEqual(panelui.arrow_move("Down", False), "next")
        self.assertEqual(panelui.arrow_move("KP_Up", False), "prev")
        self.assertIsNone(panelui.arrow_move("Left", False))
        self.assertIsNone(panelui.arrow_move("Down", True))     # a slider keeps its arrows
        self.assertIsNone(panelui.arrow_move("a", False))


def reading(level="ok", some=0.0, full=0.0, avail=8 << 30):
    return {"total": 32 << 30, "used": (32 << 30) - avail, "available": avail, "cached": 0,
            "swap_total": 8 << 30, "swap_used": 1 << 30, "some": some, "full": full,
            "level": level, "percent": 50.0}


class MemoryPillTest(unittest.TestCase):
    def test_hidden_while_calm(self):
        self.assertEqual(mem.pill(reading())["text"], "")
        self.assertIsNone(mem.level_class("ok"))

    def test_levels(self):
        self.assertEqual(mem.pill(reading("warning", some=7))["class"], "warn")
        self.assertEqual(mem.pill(reading("critical", full=3))["class"], "crit")

    def test_text_is_the_stall_else_what_is_left(self):
        self.assertIn("12% wait", mem.pill_text(reading("warning", some=12.3)))
        self.assertIn("free", mem.pill_text(reading("warning", avail=1 << 30)))

    def test_top_rss_sums_names(self):
        rows = [(1, "firefox", 300), (2, "Web Content", 100), (3, "Web Content", 250),
                (4, "kitty", 50), (5, "a", 1), (6, "b", 2), (7, "c", 3)]
        top = mem.top_rss(rows, 3)
        self.assertEqual(top, [("Web Content", 350), ("firefox", 300), ("kitty", 50)])
        self.assertEqual(len(mem.top_rss(rows)), 5)

    def test_tooltip_lists_the_top(self):
        tip = mem.pill(reading("critical", full=3), [("firefox", 2 << 30)])["tooltip"]
        self.assertIn("critically", tip)
        self.assertIn("firefox", tip)

    def test_read_rows_from_a_fake_proc(self):
        with tempfile.TemporaryDirectory() as proc:
            os.makedirs(f"{proc}/42")
            with open(f"{proc}/42/statm", "w") as h:
                h.write("100 10 0 0 0 0 0\n")
            with open(f"{proc}/42/comm", "w") as h:
                h.write("thing\n")
            os.makedirs(f"{proc}/43")          # gone mid-walk: skipped
            self.assertEqual(mem.read_rows(proc), [(42, "thing", 10 * mem.memory.PAGE)])


ADAPTER = "/org/bluez/hci0"


def objects(powered=True, devices=()):
    out = {"/org/bluez": {"org.bluez.AgentManager1": {}},
           ADAPTER: {bt.ADAPTER: {"Powered": powered, "Address": "00:00:00:00:00:01"}}}
    for i, (name, connected, battery) in enumerate(devices):
        path = f"{ADAPTER}/dev_{i}"
        out[path] = {bt.DEVICE: {"Alias": name, "Address": f"AA:{i}", "Paired": True,
                                 "Connected": connected}}
        if battery is not None:
            out[path][bt.BATTERY] = {"Percentage": battery}
    out[f"{ADAPTER}/dev_seen"] = {bt.DEVICE: {"Name": "stranger", "Paired": False, "Connected": False}}
    return out


class BluetoothTest(unittest.TestCase):
    def test_no_adapter_is_hidden(self):
        summary = bt.summarize({})
        self.assertIsNone(summary["adapter"])
        self.assertEqual(bt.pill(summary)["text"], "")

    def test_off_and_nothing_paired_is_hidden(self):
        self.assertEqual(bt.pill(bt.summarize(objects(powered=False)))["text"], "")

    def test_off_with_devices_is_dim(self):
        out = bt.pill(bt.summarize(objects(powered=False, devices=[("Headset", False, None)])))
        self.assertEqual((out["text"], out["class"]), (bt.ICON, "off"))

    def test_summary_keeps_paired_only_connected_first(self):
        s = bt.summarize(objects(devices=[("Zeta", False, None), ("Alpha", True, 80)]))
        self.assertEqual([d["name"] for d in s["devices"]], ["Alpha", "Zeta"])
        self.assertEqual(s["devices"][0]["battery"], 80)
        self.assertTrue(s["powered"])

    def test_pill_counts_and_lowest_battery(self):
        out = bt.pill(bt.summarize(objects(devices=[("A", True, 80), ("B", True, 15), ("C", False, 5)])))
        self.assertEqual(out["text"], f"{bt.ICON} 2 · 15%")
        self.assertIn("low", out["class"])
        self.assertEqual(bt.pill(bt.summarize(objects(devices=[("A", False, None)])))["class"], "on")

    def test_device_name_falls_back(self):
        self.assertEqual(bt.device_name({"Name": "n", "Address": "x"}), "n")
        self.assertEqual(bt.device_name({"Address": "x"}), "x")

    def test_pair_command(self):
        self.assertEqual(bt.pair_command(lambda n: n == "blueman-manager"), ["blueman-manager"])
        self.assertIn("bluetooth", bt.pair_command(lambda n: n == "gnome-control-center"))
        self.assertIsNone(bt.pair_command(lambda n: None))

    def test_panel_row_text(self):
        dev = {"connected": True, "battery": 55}
        self.assertEqual(btp.device_sub(dev), "Connected · battery 55%")
        self.assertEqual(btp.device_sub(dev, busy="Disconnecting…"), "Disconnecting…")
        self.assertEqual(btp.device_sub(dev, error="boom"), "boom")
        self.assertEqual(btp.dbus_error_text(
            "GDBus.Error:org.bluez.Error.Failed: br-connection-page-timeout"), "br-connection-page-timeout")
        self.assertEqual(btp.dbus_error_text(""), "Failed")


class RebootNeededTest(unittest.TestCase):
    def test_versions_compare_as_numbers(self):
        self.assertEqual(rb.newest_kernel(["7.2.9-201.fc44.x86_64", "7.2.11-200.fc44.x86_64",
                                           "7.2.10-200.fc44.x86_64"]), "7.2.11-200.fc44.x86_64")
        self.assertIsNone(rb.newest_kernel([]))

    def test_kernel_reason(self):
        self.assertEqual(rb.kernel_reason("7.2.11-200", ["7.2.10-200", "7.2.11-200"]), "")
        self.assertIn("7.2.12-200", rb.kernel_reason("7.2.11-200", ["7.2.11-200", "7.2.12-200"]))
        # Running something newer than any installed (a hand-built one): no nag.
        self.assertEqual(rb.kernel_reason("7.3.0-1", ["7.2.11-200"]), "")
        self.assertEqual(rb.kernel_reason("7.2.11-200", []), "")

    def test_needs_restarting(self):
        out = ("Core libraries or services have been updated since boot-up:\n"
               "  * linux-firmware\n  * glibc\n\nReboot is required\n")
        self.assertEqual(rb.parse_needs_restarting(1, out), (True, ["linux-firmware", "glibc"]))
        self.assertEqual(rb.parse_needs_restarting(0, "No core libraries..."), (False, []))
        self.assertEqual(rb.packages_reason(False, []), "")
        self.assertIn("glibc", rb.packages_reason(True, ["glibc"]))
        self.assertIn("2 more", rb.packages_reason(True, list("abcdef")))

    def test_cache_freshness(self):
        self.assertTrue(rb.fresh({"at": 1000}, 1500, 1800))
        self.assertFalse(rb.fresh({"at": 1000}, 3000, 1800))
        self.assertFalse(rb.fresh({}, 1000))

    def test_reasons_text(self):
        self.assertEqual(rb.reasons_text([]), "")
        self.assertEqual(rb.reasons_text(["Kernel x is installed.", "", "a\nb"]),
                         "Kernel x is installed.\na b")

    def test_installed_kernels_need_a_vmlinuz(self):
        with tempfile.TemporaryDirectory() as root:
            for name, real in (("7.2.11-200", True), ("7.2.12-1", False)):
                os.makedirs(os.path.join(root, name))
                if real:
                    open(os.path.join(root, name, "vmlinuz"), "w").close()
            self.assertEqual(rb.installed_kernels(root), ["7.2.11-200"])

    def test_card_lines(self):
        self.assertIn("Nothing", rbp.explain({"reasons": [], "checker": True})[0])
        lines = rbp.explain({"reasons": ["r"], "checker": False, "checked_at": 1.0})
        self.assertEqual(lines[0], "r")
        self.assertIn("needs-restarting", lines[1])
        # Not asked yet is not "not installed".
        waiting = rbp.explain({"reasons": [], "checker": False, "checked_at": None})
        self.assertNotIn("not installed", " ".join(waiting))
        self.assertEqual(rbp.REBOOT, ["systemctl", "reboot"])

    def test_the_badge_signal_is_the_updates_pill(self):
        bs = helpers.import_script("bar_signals.py")
        self.assertNotIn("reboot", bs.SIGNALS)
        self.assertEqual(bs.SIGNALS[rbp.BADGE_SIGNAL][2], ("custom/updates",))

    def test_updates_card_embeds_the_section(self):
        with open(os.path.join(WAYBAR_SCRIPTS, "updates_panel.py")) as handle:
            text = handle.read()
        self.assertIn("import reboot_panel", text)
        self.assertIn('reboot_panel.RestartSection("RESTART", self.quit)', text)
        self.assertTrue(hasattr(rbp, "RestartSection"))
        # The section's first draw reads the cache; needs-restarting only in a thread.
        with open(os.path.join(WAYBAR_SCRIPTS, "reboot_panel.py")) as handle:
            panel_text = handle.read()
        self.assertIn("reboot_needed.status(run=False)", panel_text)
        self.assertIn("threading.Thread(target=work", panel_text)

    def test_no_reboot_pill(self):
        with open(os.path.join(WAYBAR, "config")) as handle:
            config = handle.read()
        self.assertNotIn('"custom/reboot"', config)
        with open(os.path.join(WAYBAR, "style.css")) as handle:
            self.assertNotIn("#custom-reboot", handle.read())


class UpdatesBadgeTest(unittest.TestCase):
    """updates.sh with dnf, flatpak and the reboot check stubbed on PATH:
    the restart badge shows in every state, and only when one is due."""

    def run_updates(self, dnf_rc, dnf_out, reasons):
        import json
        import stat
        import subprocess
        with tempfile.TemporaryDirectory(dir=helpers.SCRATCH) as tmp:
            stubs = {"dnf": f"printf '%s' '{dnf_out}'\nexit {dnf_rc}\n", "flatpak": "exit 0\n",
                     "rb": "".join(f"echo '{r}'\n" for r in reasons)}
            for name, body in stubs.items():
                path = os.path.join(tmp, name)
                with open(path, "w") as handle:
                    handle.write("#!/bin/sh\n" + body)
                os.chmod(path, stat.S_IRWXU)
            env = dict(os.environ, PATH=tmp + os.pathsep + os.environ["PATH"], XDG_RUNTIME_DIR=tmp,
                       UPDATES_REBOOT_CHECK=os.path.join(tmp, "rb"))
            out = subprocess.run(["bash", os.path.join(WAYBAR_SCRIPTS, "updates.sh")], env=env,
                                 capture_output=True, text=True, timeout=30).stdout
        return json.loads(out)

    def test_up_to_date_and_due(self):
        out = self.run_updates(0, "", ["Kernel 7.3 is installed; 7.2 is running."])
        self.assertEqual(out["class"], ["updated", "reboot"])
        self.assertTrue(out["text"].endswith("\uf2f9"))
        self.assertIn("Restart needed", out["tooltip"])
        self.assertIn("Kernel 7.3", out["tooltip"])

    def test_pending_and_due_escapes(self):
        out = self.run_updates(100, "foo.x86_64 1.2-3 updates\n", ["Updated since boot: a & <b>."])
        self.assertEqual(out["class"], ["pending", "reboot"])
        self.assertIn(" 1 \uf2f9", out["text"])
        self.assertIn("a &amp; &lt;b&gt;.", out["tooltip"])

    def test_no_restart_no_badge(self):
        out = self.run_updates(0, "", [])
        self.assertEqual(out["class"], ["updated"])
        self.assertNotIn("\uf2f9", out["text"])
        self.assertNotIn("Restart", out["tooltip"])


class AwakePillTest(unittest.TestCase):
    def test_should_ask(self):
        self.assertTrue(aw.should_ask(None, (1, 2), 0, 10))           # appeared
        self.assertTrue(aw.should_ask((1, 2), None, 0, 10))           # went
        self.assertFalse(aw.should_ask(None, None, 0, 1000))          # still off: never
        self.assertFalse(aw.should_ask((1, 2), (1, 2), 100, 130))     # on, recently asked
        self.assertTrue(aw.should_ask((1, 2), (1, 2), 100, 161))      # on, recheck due
        self.assertTrue(aw.should_ask((1, 2), (1, 2), 100, 121, until=120))   # timed end passed
        self.assertFalse(aw.should_ask((1, 2), (1, 2), 125, 130, until=120))  # asked after it

    def test_pill(self):
        self.assertEqual(aw.pill(None)["text"], "")
        self.assertEqual(aw.pill({"on": False})["text"], "")
        self.assertEqual(aw.pill({"on": True, "until": None})["class"], "on")
        until = time.mktime((2026, 1, 1, 18, 30, 0, 0, 0, -1))
        self.assertIn("18:30", aw.pill({"on": True, "until": until})["text"])

    def test_file_mark(self):
        self.assertIsNone(aw.file_mark("/nonexistent/keep-awake.json"))


class NetworkVpnTest(unittest.TestCase):
    def test_terse_split(self):
        self.assertEqual(net.split_terse(r"Office\: VPN:vpn"), ["Office: VPN", "vpn"])
        self.assertEqual(net.split_terse("a:b:c"), ["a", "b", "c"])

    def test_active_vpns(self):
        text = "Wired connection 1:802-3-ethernet\nlo:loopback\nwg-home:wireguard\nWork:vpn\n"
        self.assertEqual(net.parse_active_vpns(text), ["wg-home", "Work"])
        self.assertEqual(net.parse_active_vpns(""), [])

    def test_pill_with_a_vpn(self):
        out = net.pill("enp7s0", "10.0.0.2/24", vpns=["wg-home"])
        self.assertTrue(out["text"].endswith(f"{net.ICON_VPN} wg-home"))
        self.assertEqual(out["class"], ["connected", "vpn"])
        self.assertTrue(net.is_connected(out))
        self.assertEqual(net.pill("enp7s0", "10.0.0.2/24")["class"], "connected")
        self.assertIn("+1", net.vpn_suffix(["a", "b"]))
        self.assertIn("…", net.vpn_suffix(["a-very-long-tunnel-name"]))
        self.assertEqual(net.vpn_suffix([]), "")

    def test_icon_style(self):
        """bar.network=icon (moe, or any bar on a narrow screen): the
        interface's glyph alone, the SSID and signal on hover; offline,
        "Available" with networks in range. The usual pill is unchanged and
        has no tooltip."""
        out = net.pill("wlp1s0", "10.0.0.2/24", "-60 dBm", True, style="icon", ssid="Café & <5G>")
        self.assertEqual(out["text"], net.ICON_WIFI)
        self.assertEqual(out["tooltip"], "Café &amp; &lt;5G&gt; · 80%")
        self.assertEqual(out["class"], ["connected", "icon"])
        self.assertTrue(net.is_connected(out))
        vpn = net.pill("wlp1s0", "", "-60 dBm", True, ["wg"], style="icon", ssid="home")
        self.assertEqual(vpn["tooltip"], "home · 80%")
        self.assertEqual(vpn["class"], ["connected", "vpn", "icon"])
        self.assertEqual(net.pill(None, "", style="icon", radio=True, available=True),
                         {"text": net.ICON_WIFI, "class": ["disconnected", "icon"], "tooltip": "Available"})
        self.assertEqual(net.pill(None, "", style="icon", radio=True)["tooltip"], "Disconnected")
        self.assertEqual(net.pill(None, "", style="icon")["text"], net.ICON_GLOBE)   # no radio
        plain = net.pill("wlp1s0", "", "-60 dBm", True)
        self.assertEqual(plain["text"], f"Wi-Fi (80%) {net.ICON_WIFI}")
        self.assertNotIn("tooltip", plain)
        wired = net.pill("enp7s0", "10.0.0.2/24", style="icon")
        self.assertEqual(wired["text"], net.ICON_ETHERNET)
        self.assertEqual(wired["tooltip"], "enp7s0 · 10.0.0.2")
        self.assertIn("10.0.0.2", net.pill("enp7s0", "10.0.0.2/24")["text"])

    def test_bar_style(self):
        with tempfile.NamedTemporaryFile("w", suffix=".conf", delete=False) as fh:
            fh.write("# GENERATED\nclock=\nnetwork=icon\n")
        try:
            self.assertEqual(net.bar_style(fh.name), "icon")
            with open(fh.name, "w") as out:
                out.write("network=sparkles\n")
            self.assertEqual(net.bar_style(fh.name), "")
        finally:
            os.unlink(fh.name)
        self.assertEqual(net.bar_style("/nonexistent/bar.conf"), "")
        self.assertEqual(tuple(theme.BAR_NETWORK), net.STYLES)

    def test_barfit_narrow(self):
        mons = [{"name": "eDP-1", "width": 1920, "height": 1080, "scale": 1, "transform": 0},
                {"name": "DP-1", "width": 3440, "height": 1440, "scale": 1, "transform": 0},
                {"name": "DP-2", "width": 5120, "height": 2880, "scale": 2, "transform": 0},
                {"name": "DP-3", "width": 3840, "height": 2160, "scale": 1, "transform": 1}]
        self.assertTrue(barfit.narrow("eDP-1", mons))
        self.assertFalse(barfit.narrow("DP-1", mons))
        self.assertFalse(barfit.narrow("DP-2", mons))     # 2560 logical: room enough
        self.assertTrue(barfit.narrow("DP-3", mons))      # rotated: 2160 wide
        self.assertFalse(barfit.narrow("HDMI-A-9", mons))  # not there: the usual bar

    def test_meters(self):
        """barfit.vbars: 4 segments of 25%, any load lights the first."""
        self.assertEqual([barfit.lit(v) for v in (0, 1, 25, 26, 50, 74, 75, 76, 100, 250, "x")],
                         [0, 1, 1, 2, 2, 3, 3, 4, 4, 4, 0])
        m = barfit.vbars([60], "#123456")
        rows = m[len(barfit.VB_OPEN):-len("</span>")].split("\n")
        self.assertEqual(len(rows), 4)
        self.assertEqual(["fgalpha" in r for r in rows], [True, False, False, False])   # top unlit
        self.assertIn("color='#123456'", rows[0])
        self.assertEqual(len(barfit.vbars([10, 90]).split("\n")[0].split("</span> <span")), 2)
        self.assertEqual(len(barfit.vbars([50], cap=True).split("\n")), 5)

    def test_meters_shell_and_python_agree(self):
        script = os.path.join(WAYBAR_SCRIPTS, "vbars.sh")
        for vals in (["0", "100"], ["14", "60"], ["33"]):
            out = subprocess.run(["bash", "-c", f'. "{script}"; vbars "#abcdef" t {" ".join(vals)}; '
                                  'printf %s "$t"'], capture_output=True, text=True, timeout=10).stdout
            self.assertEqual(out.replace("\\n", "\n"), barfit.vbars(vals, "#abcdef"), vals)

    def test_battery_icons_are_barfits(self):
        """waybar/config's battery format-icons are vbars(cap=True) for 25,
        50, 75 and 100 -- regenerated by hand when the meters change."""
        with open(os.path.join(WAYBAR, "config")) as fh:
            text = fh.read()
        block = text[text.index('"battery": {'):]
        block = block[block.index('"format-icons": ['):block.index("],")]
        icons = [json.loads(line.strip().rstrip(",")) for line in block.splitlines()[1:] if line.strip()]
        self.assertEqual(icons, [barfit.vbars([v], cap=True) for v in (25, 50, 75, 100)])

    def test_disk_meter(self):
        disk = load("disk")
        disks = [("nvme0n1", [{"mountpoints": ["/"], "fssize": "100", "fsused": "40"},
                              {"mountpoints": ["/mnt/big"], "fssize": "100", "fsused": "97"}])]
        saved = disk.read_disks
        disk.read_disks = lambda: disks
        try:
            narrow = disk.pill(narrow=True)
            wide = disk.pill()
        finally:
            disk.read_disks = saved
        self.assertEqual(narrow["text"], barfit.vbars([40]))
        self.assertEqual(narrow["class"], ["critical", "meters"])
        self.assertTrue(wide["text"].startswith("40%"))

    def test_back_online_with_a_vpn_class(self):
        self.assertTrue(net.back_online({"class": "disconnected"}, {"class": ["connected", "vpn"]}))
        self.assertFalse(net.back_online({"class": ["connected", "vpn"]}, {"class": "connected"}))

    def test_panel_splits_vpns_out(self):
        conns = [{"type": "802-3-ethernet", "name": "w"}, {"type": "wireguard", "name": "wg"},
                 {"type": "vpn", "name": "v"}, {"type": "802-11-wireless", "name": "f"}]
        others, vpns = netp.split_vpns(conns)
        self.assertEqual([c["name"] for c in others], ["w", "f"])
        self.assertEqual([c["name"] for c in vpns], ["wg", "v"])


class NotificationsBellTest(unittest.TestCase):
    def test_no_click_hints_and_dot_separators(self):
        tip = notif.tooltip([], 2, 9)
        self.assertNotIn("Click", tip)
        self.assertIn(" · 2 unread · 9 in history", tip)
        self.assertIn("island", notif.tooltip(["island"], 0, 0))
        self.assertIn("Do Not Disturb", notif.tooltip(["do-not-disturb"], 0, 0))

    def test_dnd_is_added_or_removed_never_toggled(self):
        self.assertEqual(notif.dnd_flag(["default"]), "-a")
        self.assertEqual(notif.dnd_flag(["default", "do-not-disturb"]), "-r")


class RememberLayoutTest(unittest.TestCase):
    def screen(self, name, **kw):
        info = {"name": name, "resolution": "1920x1080", "rate": "60.00", "scale": "1", "transform": 0,
                "x": 0, "y": 0, "enabled": True, "mirror_of": "", "chosen": {}}
        info.update(kw)
        return info

    def test_live_layout_spelling(self):
        self.assertEqual(disp.live_layout(self.screen("A", x=-1600, y=-549, transform=1, scale="0.8")),
                         {"mode": "1920x1080", "rate": "60.00", "scale": "0.8", "transform": "1",
                          "position": "-1600x-549"})

    def test_plan_skips_pinned_off_and_mirrored(self):
        pinned = self.screen("P", chosen={"mode": "1920x1080", "rate": "60.00", "scale": "1",
                                          "transform": "0", "position": "0x0"})
        plan = disp.remember_plan([self.screen("A"), pinned, self.screen("Off", enabled=False),
                                   self.screen("M", mirror_of="A")])
        self.assertEqual([name for name, _ in plan], ["A"])
        self.assertIn("position=0x0", plan[0][1])
        self.assertTrue(all(pair.split("=")[0] in disp.SCREEN_KEYS for pair in plan[0][1]))


class PhaseOneFollowupsTest(unittest.TestCase):
    def test_doctor_tooltip_has_no_click_hint(self):
        tip = doctor.bar([{"level": "fail", "text": "x.service failed"}])["tooltip"]
        self.assertNotIn("Click", tip)

    def test_every_monitor_colour_is_defined(self):
        self.assertIn("mon4", tint.COLORS)
        with open(os.path.join(WAYBAR, "style.css")) as handle:
            css = handle.read()
        for name in tint.COLORS + (tint.FALLBACK,):
            for suffix in ("", "-dim"):
                self.assertRegex(css, rf"@define-color {re.escape(name + suffix)}\s", name + suffix)

    def test_every_panel_has_its_script(self):
        for name, script in panel.PANELS.items():
            self.assertTrue(os.path.exists(os.path.join(WAYBAR_SCRIPTS, script)), name)
        self.assertIn("bluetooth", panel.PANELS)
        self.assertIn("reboot", panel.PANELS)


if __name__ == "__main__":
    unittest.main()
