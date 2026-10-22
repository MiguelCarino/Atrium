"""system-info.py (the About this computer page's backend): the parsers and
formatters, the hiding of identifiers, the report and where it is saved.
Pure functions and scratch folders only: no command is run (the gatherers
are not called), nothing reaches the clipboard or ~/Documents."""
import datetime
import os
import tempfile
import unittest
from unittest import mock

from helpers import SCRATCH, import_script

si = import_script("system-info.py")


class Sizes(unittest.TestCase):
    def test_human_bytes(self):
        self.assertEqual(si.human_bytes(4096805658624), "4.10 TB")
        self.assertEqual(si.human_bytes(480103981056), "480 GB")
        self.assertEqual(si.human_bytes(33538088960, True), "31.2 GiB")
        self.assertEqual(si.human_bytes(512), "512 B")
        self.assertEqual(si.human_bytes(None), "?")

    def test_installed_ram_rounds_up_to_what_is_on_the_box(self):
        self.assertEqual(si.installed_ram(int(31.2 * 2 ** 30)), "32 GB RAM")
        self.assertEqual(si.installed_ram(int(15.5 * 2 ** 30)), "16 GB RAM")
        self.assertEqual(si.installed_ram(int(62.7 * 2 ** 30)), "64 GB RAM")
        self.assertEqual(si.installed_ram(int(1.9 * 2 ** 30)), "1.9 GB RAM")

    def test_duration(self):
        self.assertEqual(si.duration(66300), "18 h 25 min")
        self.assertEqual(si.duration(300), "5 min")
        self.assertEqual(si.duration(86400 + 3600), "1 day 1 h 0 min")
        self.assertEqual(si.duration(5 * 86400 + 7200), "5 days 2 h")


class Firmware(unittest.TestCase):
    def test_dmi_date(self):
        self.assertEqual(si.dmi_date("08/08/2025"), "2025-08-08")
        self.assertEqual(si.dmi_date("1/2/2024"), "2024-01-02")
        self.assertEqual(si.dmi_date("2024-01-02"), "2024-01-02")

    def test_self_built_pc_is_named_after_its_board(self):
        dmi = {"sys_vendor": "ASUS", "product_name": "System Product Name", "product_version": "System Version",
               "board_vendor": "ASUSTeK COMPUTER INC.", "board_name": "ROG STRIX B550-F GAMING (WI-FI)"}
        self.assertEqual(si.pick_model(dmi), "ASUS ROG STRIX B550-F GAMING (WI-FI)")

    def test_laptop_is_named_after_its_product(self):
        dmi = {"sys_vendor": "LENOVO", "product_name": "21CB", "product_version": "ThinkPad X1 Carbon Gen 10",
               "board_name": "21CB"}
        self.assertEqual(si.pick_model(dmi), "LENOVO 21CB ThinkPad X1 Carbon Gen 10")
        self.assertEqual(si.pick_model({"sys_vendor": "Framework", "product_name": "Laptop 13"}),
                         "Framework Laptop 13")
        self.assertEqual(si.pick_model({}), "unknown model")

    def test_kernel_build_date(self):
        self.assertEqual(si.kernel_build_date("#1 SMP PREEMPT_DYNAMIC Thu Oct 15 15:58:58 UTC 2026"), "2026-10-15")
        self.assertEqual(si.kernel_build_date("#1 SMP"), "")


class Parsers(unittest.TestCase):
    def test_os_release(self):
        kv = si.parse_kv('NAME="Fedora Linux"\nVERSION_ID=44\n# comment\nSUPPORT_END=2027-05-19\n')
        self.assertEqual(kv, {"NAME": "Fedora Linux", "VERSION_ID": "44", "SUPPORT_END": "2027-05-19"})

    def test_lscpu(self):
        data = {"lscpu": [{"field": "Model name:", "data": "AMD Ryzen 9 5900X",
                           "children": [{"field": "Thread(s) per core:", "data": "2"}]},
                          {"field": "L3 cache:", "data": "64 MiB (2 instances)"}]}
        out = si.parse_lscpu(data)
        self.assertEqual(out["Model name"], "AMD Ryzen 9 5900X")
        self.assertEqual(out["Thread(s) per core"], "2")
        self.assertEqual(si.parse_lscpu(None), {})

    def test_cpu_topology_counts_cores_and_threads(self):
        root = tempfile.mkdtemp(dir=SCRATCH)
        for cpu, core in ((0, 0), (1, 1), (2, 0), (3, 1)):          # 2 cores, 2 threads each
            top = os.path.join(root, f"cpu{cpu}", "topology")
            os.makedirs(top)
            for name, value in (("physical_package_id", "0"), ("core_id", str(core))):
                with open(os.path.join(top, name), "w") as handle:
                    handle.write(value)
        os.makedirs(os.path.join(root, "cpufreq"))                  # not a CPU
        self.assertEqual(si.cpu_topology(root), (1, 2, 4))

    def test_meminfo_swaps_zram(self):
        mem = si.meminfo("MemTotal:       32752040 kB\nMemAvailable:   18450384 kB\nHugePages_Total:       0\n")
        self.assertEqual(mem["MemTotal"], 32752040 * 1024)
        self.assertEqual(mem["HugePages_Total"], 0)
        swaps = si.parse_swaps("Filename\tType\tSize\tUsed\tPriority\n/dev/zram0 partition 8388604 3578508 100\n")
        self.assertEqual(swaps, [{"name": "/dev/zram0", "type": "partition", "size": 8388604 * 1024,
                                  "used": 3578508 * 1024, "prio": 100}])
        z = si.parse_zramctl("/dev/zram0 lzo-rle 8589934592 3441561600 1394340298 1719476224\n")
        self.assertEqual(z["/dev/zram0"]["algorithm"], "lzo-rle")
        self.assertEqual(z["/dev/zram0"]["compr"], 1394340298)

    def test_nvidia(self):
        line = ("NVIDIA GeForce RTX 4090, 615.78.08, 24564, 2023, 00000000:08:00.0, 34, 32.92, 450.00, 4, 16, 1, "
                "3120, 95.02.3C.00.78, [N/A]\n")
        g = si.parse_nvidia_csv(line)[0]
        self.assertEqual(g["name"], "NVIDIA GeForce RTX 4090")
        self.assertEqual(g["memory.total"], "24564")
        self.assertEqual(g["utilization.gpu"], "")
        self.assertEqual(si.parse_nvidia_csv("garbage\n"), [])
        self.assertEqual(si.cuda_version("| NVIDIA-SMI 615.78.08   KMD Version: 615.78.08   CUDA UMD Version: 13.4 |"),
                         "13.4")
        self.assertEqual(si.cuda_version("| Driver Version: 550.1   CUDA Version: 12.4 |"), "12.4")
        self.assertEqual(si.short_bus("00000000:08:00.0"), "08:00.0")

    def test_lspci(self):
        out = si.parse_lspci_mm('08:00.0 "VGA compatible controller" "NVIDIA Corporation" "AD102 [GeForce RTX 4090]" '
                                '-ra1 -p00 "NVIDIA Corporation" "Device 167c"\n')
        self.assertEqual(out, [{"bus": "08:00.0", "class": "VGA compatible controller",
                                "vendor": "NVIDIA Corporation", "device": "AD102 [GeForce RTX 4090]"}])

    def test_vulkan_summary(self):
        text = ("GPU0:\n\tapiVersion = 1.4.351\n\tdeviceType = PHYSICAL_DEVICE_TYPE_DISCRETE_GPU\n"
                "\tdeviceName = NVIDIA GeForce RTX 4090\n\tdriverName = NVIDIA\n\tdriverInfo = 615.78.08\n"
                "GPU1:\n\tapiVersion = 1.4.354\n\tdeviceName = llvmpipe\n\tdriverName = llvmpipe\n")
        devs = si.parse_vulkan_summary(text)
        self.assertEqual([d["deviceName"] for d in devs], ["NVIDIA GeForce RTX 4090", "llvmpipe"])
        self.assertEqual(devs[1]["apiVersion"], "1.4.354")

    def test_resolvectl(self):
        dns = si.parse_resolvectl_dns("Global:\nLink 2 (enp7s0): 192.168.0.1 1.1.1.1\nLink 3 (wlp6s0):\n")
        self.assertEqual(dns, {"enp7s0": ["192.168.0.1", "1.1.1.1"]})

    def test_rpm_versions(self):
        text = ("gtk3\t3.24.52\ngtk3\t3.24.52\npackage nvidia-driver is not installed\nwaybar\t0.15.0\n")
        self.assertEqual(si.parse_rpm_versions(text), {"gtk3": "3.24.52", "waybar": "0.15.0"})
        self.assertEqual(si.version_from_output("Hyprlock version v0.9.6"), "0.9.6")

    def test_repos(self):
        texts = ["[fedora]\nname=Fedora\nenabled=1\n[fedora-debuginfo]\nenabled=0\n",
                 "[copr:copr.fedorainfracloud.org:owner:Proj]\nbaseurl=x\n"]
        repos = si.parse_repos(texts)
        self.assertEqual(repos, ["fedora", "copr:copr.fedorainfracloud.org:owner:Proj"])
        self.assertEqual(si.short_repo(repos[1]), "copr owner/Proj")
        self.assertEqual(si.short_repo("updates"), "updates")

    def test_global_ipv6(self):
        self.assertTrue(si.is_global_ipv6("2001:db8::1"))
        self.assertFalse(si.is_global_ipv6("fe80::1"))
        self.assertFalse(si.is_global_ipv6("fd12::1"))
        self.assertFalse(si.is_global_ipv6("::1"))
        self.assertFalse(si.is_global_ipv6("192.168.0.1"))


class Displays(unittest.TestCase):
    MON = {"name": "DP-1", "make": "Acme Corporation", "model": "Wide 34", "serial": "SN123",
           "width": 3440, "height": 1440, "refreshRate": 143.97, "x": 0, "y": 0, "scale": 1.0, "transform": 0,
           "physicalWidth": 810, "physicalHeight": 350, "currentFormat": "XBGR2101010", "vrr": False,
           "colorManagementPreset": "hdredid", "sdrMaxLuminance": 382, "focused": True,
           "availableModes": ["3440x1440@180.00Hz", "3440x1440@144.00Hz", "2560x1440@60.00Hz"]}

    def test_best_mode(self):
        self.assertEqual(si.best_mode(self.MON["availableModes"]), "3440×1440 @ 180 Hz")
        self.assertEqual(si.best_mode([]), "")

    def test_monitor_row(self):
        r = si.monitor_row(self.MON)
        self.assertEqual(r["name"], "DP-1")
        self.assertEqual(r["value"], "3440×1440 @ 144 Hz")
        text = "\n".join(r["lines"])
        self.assertIn("HDR on (hdredid)", text)
        self.assertIn("10-bit", text)
        self.assertIn('34.7"', text)
        self.assertIn("best mode it offers: 3440×1440 @ 180 Hz", text)
        self.assertEqual(r["secret"], {"serial number": "SN123"})

    def test_rotated_sdr_and_disabled(self):
        r = si.monitor_row(dict(self.MON, transform=1, colorManagementPreset="srgb", currentFormat="XRGB8888"))
        text = "\n".join(r["lines"])
        self.assertIn("rotated 90°", text)
        self.assertIn("SDR", text)
        self.assertIn("8-bit", text)
        self.assertEqual(si.monitor_row(dict(self.MON, disabled=True))["value"], "off")


class Storage(unittest.TestCase):
    def test_disk_kind(self):
        self.assertEqual(si.disk_kind({"name": "nvme0n1", "tran": "nvme"}), "NVMe SSD")
        self.assertEqual(si.disk_kind({"name": "sdb", "tran": "sata", "rota": True}), "HDD")
        self.assertEqual(si.disk_kind({"name": "sda", "tran": "sata", "rota": False}), "SSD")
        self.assertEqual(si.disk_kind({"name": "sdc", "tran": "usb"}), "USB drive")

    def test_fs_lines(self):
        with mock.patch.object(si, "usage", return_value=(25 * 10 ** 9, 100 * 10 ** 9)):
            line = si.fs_line({"name": "nvme0n1p3", "size": 2 * 10 ** 12, "fstype": "btrfs", "label": "fedora",
                               "mountpoints": ["/home", "/"]}, 0)
        self.assertIn("btrfs “fedora”  on /, /home", line)
        self.assertIn("(25 %)", line)
        self.assertIn("LVM physical volume (no active volume)",
                      si.fs_line({"name": "sda", "size": 1, "fstype": "LVM2_member"}, 0))
        self.assertIn("locked", si.fs_line({"name": "sdb1", "size": 1, "fstype": "crypto_LUKS"}, 1))
        self.assertIn("not mounted", si.fs_line({"name": "sdb2", "size": 1, "fstype": "ext4"}, 1))

    def test_walk_is_depth_first(self):
        disk = {"children": [{"name": "p1", "children": [{"name": "lv"}]}, {"name": "p2"}]}
        self.assertEqual([(n["name"], d) for n, d in si.walk(disk)], [("p1", 0), ("lv", 1), ("p2", 0)])

    def test_mount_points_undo_the_kernels_escapes(self):
        path = os.path.join(SCRATCH, "about-mountinfo")
        with open(path, "w") as handle:
            handle.write("29 1 0:27 /root / rw - btrfs /dev/x rw\n"
                         "90 29 0:44 / /mnt/My\\040Disk rw - btrfs /dev/y rw\n")
        self.assertEqual(si.mount_points(path), {"/", "/mnt/My Disk"})

    def test_find_subvolumes_uses_lstat_and_the_mount_list(self):
        # A fake tree where some directories "are" subvolumes: lstat says
        # inode 256 for them (what btrfs answers; scandir's own inode would
        # be the subvolume id, which is what used to hide every one of them).
        root = tempfile.mkdtemp(dir=SCRATCH)
        for d in ("usr/lib", ".snapshots/1/snapshot", "var/lib/machines", "data/vm", "mnt/other/sub"):
            os.makedirs(os.path.join(root, d))
        subvols = {os.path.join(root, d) for d in (".snapshots", ".snapshots/1/snapshot", "var/lib/machines",
                                                    "data/vm", "mnt/other/sub")}
        real_lstat = os.lstat

        def fake_lstat(path, *a, **k):
            st = real_lstat(path, *a, **k)
            if path in subvols:
                fields = list(st)
                fields[1] = 256          # st_ino
                st = os.stat_result(fields)
            return st
        with mock.patch.object(si.os, "lstat", side_effect=fake_lstat):
            found = si.find_subvolumes(root, mounts={os.path.join(root, "mnt/other")})
        self.assertEqual(sorted(found), sorted([os.path.join(root, d) for d in (
            ".snapshots", ".snapshots/1/snapshot", "var/lib/machines", "data/vm")]))


class Kernel(unittest.TestCase):
    def test_taint_line(self):
        self.assertEqual(si.taint_line(0), "")
        self.assertIn("out-of-tree module, unsigned module", si.taint_line(12288))
        self.assertIn("third-party driver", si.taint_line(12288))
        self.assertNotIn("journalctl", si.taint_line(12288))
        bad = si.taint_line(4096 + 512)
        self.assertIn("kernel warning", bad)
        self.assertIn("journalctl", bad)
        self.assertIn("flag 30", si.taint_line(1 << 30))


class MonitorSerial(unittest.TestCase):
    def test_description_fallback_leaves_the_serial_out(self):
        r = si.monitor_row({"name": "DP-3", "width": 1920, "height": 1080, "refreshRate": 60.0,
                            "description": "Acme Screen 27 SN999", "serial": "SN999"})
        self.assertIn("Acme Screen 27", r["lines"][0])
        self.assertNotIn("SN999", "\n".join(r["lines"]))
        self.assertEqual(r["secret"], {"serial number": "SN999"})


class Report(unittest.TestCase):
    SECTIONS = [{"id": "network", "title": "Network", "facts": {},
                 "rows": [si.make_row("enp7s0", "1 Gb/s", ["IPv4 10.0.0.2/24", ""],
                                      {"MAC address": "aa:bb:cc:dd:ee:ff"})]},
                {"id": "computer", "title": "Computer", "facts": {"host": "box", "model": "Board X"},
                 "rows": [si.make_row("Board X", "Desktop", ["host name box"])]},
                {"id": "cpu", "title": "Processor", "facts": {"cpu": "Ryzen"},
                 "rows": [si.make_row("Broken", "", ["boom"], error=True)]}]

    def test_identifiers_hidden_unless_revealed(self):
        when = datetime.datetime(2026, 10, 20, 3, 40)
        hidden = si.report_text(self.SECTIONS, False, when)
        self.assertNotIn("aa:bb:cc", hidden)
        self.assertIn("MAC address: (hidden)", hidden)
        self.assertIn("left out", hidden)
        shown = si.report_text(self.SECTIONS, True, when)
        self.assertIn("MAC address: aa:bb:cc:dd:ee:ff", shown)
        self.assertTrue(hidden.startswith("System report: box, 2026-10-20 03:40\nbox  ·  Board X  ·  Ryzen\n"))
        # Report order, not arrival order; empty lines dropped; errors marked.
        self.assertLess(hidden.index("COMPUTER"), hidden.index("PROCESSOR"))
        self.assertLess(hidden.index("PROCESSOR"), hidden.index("NETWORK"))
        self.assertIn("  ! Broken", hidden)
        self.assertNotIn("\n    \n", hidden)

    def test_public_json(self):
        out = si.public_json(self.SECTIONS)
        self.assertEqual(out[0]["rows"][0]["secret"], {"MAC address": "(hidden)"})
        self.assertEqual(self.SECTIONS[0]["rows"][0]["secret"]["MAC address"], "aa:bb:cc:dd:ee:ff")
        self.assertIs(si.public_json(self.SECTIONS, True), self.SECTIONS)

    def test_summary(self):
        self.assertEqual(si.summary(self.SECTIONS), "box  ·  Board X  ·  Ryzen")
        self.assertEqual(si.summary(self.SECTIONS, host=False), "Board X  ·  Ryzen")

    def test_gather_never_raises(self):
        with mock.patch.dict(si.GATHER, {"cpu": lambda: 1 / 0}):
            s = si.gather("cpu")
        self.assertEqual(s["title"], "Processor")
        self.assertTrue(s["rows"][0]["error"])
        self.assertIn("ZeroDivisionError", s["rows"][0]["lines"][0])


class Saving(unittest.TestCase):
    def test_default_path_prefers_documents(self):
        home = tempfile.mkdtemp(dir=SCRATCH)
        when = datetime.datetime(2026, 10, 20, 3, 40)
        self.assertEqual(si.default_report_path(home, when, "my box"),
                         os.path.join(home, "system-report-my-box-2026-10-20-0340.txt"))
        os.makedirs(os.path.join(home, "Documents"))
        self.assertEqual(si.default_report_path(home, when, "box"),
                         os.path.join(home, "Documents", "system-report-box-2026-10-20-0340.txt"))

    def test_save_report_writes_atomically(self):
        path = os.path.join(tempfile.mkdtemp(dir=SCRATCH), "sub", "r.txt")
        self.assertEqual(si.save_report("hello\n", path), path)
        with open(path) as handle:
            self.assertEqual(handle.read(), "hello\n")
        self.assertEqual(os.listdir(os.path.dirname(path)), ["r.txt"])

    def test_copy_reports_failure(self):
        with mock.patch.object(si.subprocess, "run", side_effect=OSError("no wl-copy")) as run:
            self.assertFalse(si.copy_text("x"))
        self.assertEqual(run.call_args[0][0][0], "wl-copy")
        with mock.patch.object(si.subprocess, "run") as run:
            self.assertTrue(si.copy_text("x"))
        self.assertEqual(run.call_args[1]["input"], "x")


if __name__ == "__main__":
    unittest.main()


class HeroTest(unittest.TestCase):
    """The card at the top of Settings > About (settings_pages/about.py)."""

    def setUp(self):
        try:
            from settings_pages import about
        except Exception as exc:    # no GTK here
            raise unittest.SkipTest(f"settings_pages.about not importable: {exc}")
        self.about = about

    def test_empty_keeps_its_shape(self):
        facts = self.about.hero_facts({})
        self.assertEqual(len(facts["tiles"]), 8)
        self.assertTrue(all(t[3] == "…" for t in facts["tiles"]))

    def test_from_sections(self):
        I = self.about.si.ICON
        sec = lambda *rows: {"rows": [dict(r) for r in rows]}
        data = {
            "computer": sec({"name": "Acme Board X", "value": "Desktop"},
                            {"name": "Uptime", "value": "2 days", "lines": ["on since Mon"]}),
            "os": sec({"name": "Fedora Linux 44"}, {"name": "Kernel", "value": "7.2.11-200.fc44.x86_64"},
                      {"name": "Hyprland", "value": "0.56.2"}),
            "cpu": sec({"name": "Zen 9 Processor", "value": "12 cores"}),
            "memory": sec({"name": "RAM", "value": "31.2 GiB"}, {"name": "Swap zram0", "value": "8 GiB"}),
            "storage": sec({"name": "a", "value": "8.00 TB", "icon": I["disk"]},
                           {"name": "b", "value": "480 GB", "icon": I["disk"]},
                           {"name": "btrfs", "value": "6 subvolumes", "icon": I["btrfs"]}),
            "displays": sec({"name": "DP-1", "value": "3440×1440 @ 60 Hz", "icon": I["display"]},
                            {"name": "DP-2", "value": "1600×900 @ 60 Hz", "icon": I["display"]}),
        }
        facts = self.about.hero_facts(data)
        tiles = {t[0]: (t[3], t[4]) for t in facts["tiles"]}
        self.assertEqual(facts["system"], "Fedora Linux 44")
        self.assertEqual(facts["logo"], self.about.FEDORA)
        self.assertEqual(tiles["cpu"], ("Zen 9", "12 cores"))
        self.assertEqual(tiles["storage"], ("8.5 TB", "2 drives"))
        self.assertEqual(tiles["displays"], ("2 screens", "largest 3440×1440"))
        self.assertEqual(tiles["kernel"][0], "7.2.11")
        self.assertEqual(tiles["memory"], ("31.2 GiB", "swap 8 GiB"))
        self.assertEqual(tiles["desktop"][0], "Hyprland 0.56.2")
