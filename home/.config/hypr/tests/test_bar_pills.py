"""The bar's newer pills and panels, pure parts only: no window is opened,
no D-Bus or nmcli is reached, nothing is rebooted.

  panelui.py          label(), the two-click Arming rule, the keyboard walk
                      (first_match, arrow_move)
  memory_pill.py      memory-pressure pill: levels, top processes, text
  bluetooth.py        BlueZ objects -> summary -> pill; "Pair new..." pick
  bluetooth_panel.py  a device row's subtitle, D-Bus error text
  reboot_needed.py    kernel versions, needs-restarting's answer, the pill
  reboot_panel.py     the card's lines
  awake_pill.py       when to ask idle-settings.py, the pill
  network.py          VPNs in the pill; network_panel.py's VPN section
  notifications.py    the bell's tooltip (no click hints), the DND flag
  display_panel.py    "Remember this layout": which screens get written
  doctor.py, workspace-tint.py, style.css, panel.py: the phase-1 followups
"""
import importlib.util
import os
import re
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

    def test_pill(self):
        self.assertEqual(rb.pill([])["text"], "")
        out = rb.pill(["Kernel x is installed."])
        self.assertEqual(out["class"], "needed")
        self.assertIn("Kernel x", out["tooltip"])

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
