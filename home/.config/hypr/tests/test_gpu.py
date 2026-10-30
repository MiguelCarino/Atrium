"""gpu.py (the vendor-neutral GPU reader): NVML through ctypes against a fake
library (no driver needed), amdgpu / i915 / no card from fake sysfs trees,
DRM fdinfo parsing and the per-process numbers from a fake /proc, the
Intel load sampler, and the recorder's encoder pick. Nothing reads the real
/sys, /proc or the card."""
import os
import shutil
import tempfile
import unittest

import helpers

gpu = helpers.import_script("gpu.py")
MIB = 2 ** 20


def obj(ref):
    """The object behind a ctypes.byref() argument."""
    return ref._obj


class FakeNvml:
    """The NVML functions gpu.Nvml calls, filling their out-arguments the way
    the real library does. One card unless told otherwise."""

    def __init__(self, cards=1, init_ret=0):
        self.cards = cards
        self.init_ret = init_ret
        self.compute = {1001: 4096 * MIB, 1002: 600 * MIB}
        self.graphics = {1001: 4096 * MIB, 2000: gpu.NOT_AVAILABLE, 2001: 300 * MIB}
        self.samples = [(2001, 10, 40), (2001, 20, 60), (1001, 30, 5)]

    def nvmlInit_v2(self):
        return self.init_ret

    def nvmlDeviceGetCount_v2(self, count):
        obj(count).value = self.cards
        return 0

    def nvmlDeviceGetHandleByIndex_v2(self, index, handle):
        obj(handle).value = index.value + 1
        return 0

    def nvmlDeviceGetName(self, _h, buf, _n):
        buf.value = b"NVIDIA Test Card"
        return 0

    def nvmlDeviceGetPciInfo_v3(self, h, pci):
        obj(pci).busId = b"00000000:08:00.0" if h.value == 1 else b"00000000:09:00.0"
        return 0

    def nvmlDeviceGetMemoryInfo(self, _h, mem):
        m = obj(mem)
        m.total, m.used, m.free = 24 * 1024 * MIB, 6 * 1024 * MIB, 18 * 1024 * MIB
        return 0

    def nvmlDeviceGetUtilizationRates(self, _h, util):
        obj(util).gpu = 37
        return 0

    def nvmlDeviceGetTemperature(self, _h, _sensor, temp):
        obj(temp).value = 55
        return 0

    def nvmlDeviceGetPowerUsage(self, _h, mw):
        obj(mw).value = 123456
        return 0

    def nvmlDeviceGetFanSpeed(self, _h, _fan):
        return 3                                        # NOT_SUPPORTED: no fan reading

    def nvmlSystemGetDriverVersion(self, buf, _n):
        buf.value = b"615.78.08"
        return 0

    def _procs(self, table, count, infos):
        n = obj(count)
        if n.value < len(table):
            n.value = len(table)
            return gpu.NVML_ERROR_INSUFFICIENT_SIZE
        for i, (pid, used) in enumerate(table.items()):
            infos[i].pid, infos[i].usedGpuMemory = pid, used
        n.value = len(table)
        return 0

    def nvmlDeviceGetComputeRunningProcesses_v3(self, _h, count, infos):
        return self._procs(self.compute, count, infos)

    def nvmlDeviceGetGraphicsRunningProcesses_v3(self, _h, count, infos):
        return self._procs(self.graphics, count, infos)

    def nvmlDeviceGetProcessUtilization(self, _h, samples, count, _since):
        n = obj(count)
        if samples is None or n.value < len(self.samples):
            n.value = len(self.samples)
            return gpu.NVML_ERROR_INSUFFICIENT_SIZE
        for i, (pid, stamp, sm) in enumerate(self.samples):
            samples[i].pid, samples[i].timeStamp, samples[i].smUtil = pid, stamp, sm
        n.value = len(self.samples)
        return 0


class Tree:
    """A scratch / with sys/class/drm/cardN -> sys/devices/.../<pci>."""

    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="gpu-sys-", dir=helpers.SCRATCH)
        self.sys = os.path.join(self.root, "sys")
        self.proc = os.path.join(self.root, "proc")
        os.makedirs(os.path.join(self.sys, "class", "drm"))
        os.makedirs(self.proc)

    def write(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as handle:
            handle.write(text)

    def card(self, n, pci, vendor, device, driver, files=None, connectors=True):
        dev = os.path.join(self.sys, "devices", "pci0000:00", pci)
        os.makedirs(dev, exist_ok=True)
        self.write(os.path.join(dev, "vendor"), vendor + "\n")
        self.write(os.path.join(dev, "device"), device + "\n")
        drv = os.path.join(self.sys, "bus", "pci", "drivers", driver)
        os.makedirs(drv, exist_ok=True)
        os.symlink(drv, os.path.join(dev, "driver"))
        card = os.path.join(self.sys, "class", "drm", f"card{n}")
        os.makedirs(card)
        os.symlink(dev, os.path.join(card, "device"))
        if connectors:
            os.makedirs(os.path.join(self.sys, "class", "drm", f"card{n}-DP-1"))     # a connector: skipped
        bus = os.path.join(self.sys, "bus", "pci", "devices")
        os.makedirs(bus, exist_ok=True)
        if not os.path.lexists(os.path.join(bus, pci)):
            os.symlink(dev, os.path.join(bus, pci))
        for rel, text in (files or {}).items():
            self.write(os.path.join(dev, rel), text)
        return card

    def client(self, pid, fd, text, comm="app"):
        os.makedirs(os.path.join(self.proc, str(pid), "fd"), exist_ok=True)
        link = os.path.join(self.proc, str(pid), "fd", str(fd))
        if not os.path.lexists(link):
            os.symlink("/dev/dri/renderD128", link)
        self.write(os.path.join(self.proc, str(pid), "fdinfo", str(fd)), text)
        self.write(os.path.join(self.proc, str(pid), "comm"), comm + "\n")

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)


AMD_FILES = {"gpu_busy_percent": "42\n", "mem_info_vram_used": str(3 * 1024 * MIB),
             "mem_info_vram_total": str(16 * 1024 * MIB), "hwmon/hwmon3/temp1_input": "61000\n",
             "hwmon/hwmon3/power1_average": "187000000\n", "hwmon/hwmon3/pwm1": "102\n",
             "product_name": "AMD Radeon RX 7800 XT\n"}

AMD_FDINFO = """pos:\t0
flags:\t02100002
drm-driver:\tamdgpu
drm-pdev:\t0000:03:00.0
drm-client-id:\t17
drm-memory-vram:\t2097152 KiB
drm-memory-gtt:\t4096 KiB
drm-engine-gfx:\t1000000 ns
"""

XE_FDINFO = """drm-driver:\txe
drm-pdev:\t0000:00:02.0
drm-client-id:\t4
drm-total-system0:\t512 MiB
drm-resident-system0:\t500 MiB
drm-total-vram0:\t3 GiB
drm-resident-vram0:\t1 GiB
drm-engine-rcs:\t5000000000 ns
drm-engine-capacity-rcs:\t1
drm-cycles-rcs:\t28257900
"""


class Base(unittest.TestCase):
    def setUp(self):
        self.tree = Tree()
        self.saved = gpu.SYS, gpu.PROC
        gpu.SYS, gpu.PROC = self.tree.sys, self.tree.proc
        self.no_nvml = gpu.Nvml(lib=object())          # no nvmlInit at all: NVML missing

    def tearDown(self):
        gpu.SYS, gpu.PROC = self.saved
        self.tree.cleanup()


class NvmlTest(Base):
    def test_device_numbers(self):
        nv = gpu.Nvml(FakeNvml())
        self.assertTrue(nv.ok())
        d = nv.device(0)
        self.assertEqual((d["name"], d["pci"], d["util"], d["vram_used"], d["vram_total"], d["temp"]),
                         ("NVIDIA Test Card", "0000:08:00.0", 37, 6144, 24576, 55))
        self.assertEqual(d["power"], 123.5)
        self.assertIsNone(d["fan"])                     # not supported -> None, not 0
        self.assertEqual(nv.driver(), "615.78.08")

    def test_init_failure_is_no_card(self):
        nv = gpu.Nvml(FakeNvml(init_ret=9))             # NVML_ERROR_DRIVER_NOT_LOADED
        self.assertFalse(nv.ok())
        self.assertEqual(nv.count(), 0)
        self.assertEqual(gpu.gpus(nv), [])

    def test_missing_library(self):
        nv = gpu.Nvml()
        saved = gpu.NVML_LIB
        gpu.NVML_LIB = "libnot-a-real-nvml.so.0"
        try:
            self.assertFalse(nv.ok())
        finally:
            gpu.NVML_LIB = saved

    def test_processes_grow_the_buffer_and_merge_lists(self):
        fake = FakeNvml()
        fake.compute = {p: 100 * MIB for p in range(3000, 3100)}    # more than the first 64 slots
        nv = gpu.Nvml(fake)
        self.assertEqual(len(nv.processes(0, compute_only=True)), 100)

        nv = gpu.Nvml(FakeNvml())
        self.assertEqual(nv.processes(0, compute_only=True), {1001: 4096, 1002: 600})
        # graphics too: 1001 is in both lists (counted once), 2000 has no usage
        self.assertEqual(nv.processes(0), {1001: 4096, 1002: 600, 2000: 0, 2001: 300})

    def test_process_util_averages_and_remembers(self):
        nv = gpu.Nvml(FakeNvml())
        self.assertEqual(nv.process_util(0), {2001: 50, 1001: 5})
        self.assertEqual(nv.last_seen[0], 30)

    def test_gpus_pairs_nvml_with_sysfs(self):
        self.tree.card(1, "0000:08:00.0", "0x10de", "0x2684", "nvidia")
        cards = gpu.gpus(gpu.Nvml(FakeNvml()))
        self.assertEqual(len(cards), 1)                 # the sysfs card is the NVML one
        self.assertEqual(cards[0]["card"], os.path.join(self.tree.sys, "class", "drm", "card1"))
        self.assertEqual((cards[0]["source"], cards[0]["discrete"]), ("nvml", True))

    def test_nvidia_without_nvml_is_listed_without_numbers(self):
        self.tree.card(0, "0000:08:00.0", "0x10de", "0x2684", "nouveau")
        g = gpu.primary(self.no_nvml)
        self.assertEqual((g["vendor"], g["driver"], g["source"], g["util"]), ("nvidia", "nouveau", "none", None))


class SysfsTest(Base):
    def test_amd(self):
        self.tree.card(0, "0000:03:00.0", "0x1002", "0x747e", "amdgpu", AMD_FILES)
        g = gpu.primary(self.no_nvml)
        self.assertEqual((g["vendor"], g["name"], g["driver"], g["pci"]),
                         ("amd", "AMD Radeon RX 7800 XT", "amdgpu", "0000:03:00.0"))
        self.assertEqual((g["util"], g["vram_used"], g["vram_total"], g["temp"], g["power"], g["fan"]),
                         (42, 3072, 16384, 61, 187.0, 40))
        self.assertTrue(g["discrete"])
        self.assertEqual(gpu.vendor(self.no_nvml), "amd")

    def test_intel_igpu_and_amd_dgpu_order(self):
        self.tree.card(0, "0000:00:02.0", "0x8086", "0xa780", "i915",
                       {"hwmon/hwmon5/temp1_input": "48000"})
        self.tree.card(1, "0000:03:00.0", "0x1002", "0x747e", "amdgpu", AMD_FILES)
        cards = gpu.gpus(self.no_nvml)
        self.assertEqual([c["vendor"] for c in cards], ["amd", "intel"])     # discrete first
        intel = cards[1]
        self.assertFalse(intel["discrete"])
        self.assertIsNone(intel["vram_total"])          # an iGPU's memory is the RAM
        self.assertIsNone(intel["util"])                # no load file: the stream samples fdinfo
        self.assertEqual(intel["temp"], 48)

    def test_apu_is_not_discrete(self):
        files = dict(AMD_FILES, mem_info_vram_total=str(512 * MIB))
        del files["product_name"]
        self.tree.card(0, "0000:05:00.0", "0x1002", "0x15bf", "amdgpu", files)
        g = gpu.primary(self.no_nvml)
        self.assertFalse(g["discrete"])
        self.assertTrue(g["name"].startswith("AMD"))

    def test_no_card(self):
        self.assertEqual(gpu.gpus(self.no_nvml), [])
        self.assertIsNone(gpu.primary(self.no_nvml))
        self.assertEqual(gpu.vendor(self.no_nvml), "none")
        self.assertEqual(gpu.processes(nvml=self.no_nvml), {})
        self.assertEqual(gpu.process_table(nvml=self.no_nvml), [])

    def test_unknown_vendor(self):
        self.tree.card(0, "0000:00:01.0", "0x1af4", "0x1050", "virtio-pci")
        g = gpu.primary(self.no_nvml)
        self.assertEqual((g["vendor"], g["source"], g["discrete"]), ("other", "none", False))

    def test_pci_address_forms(self):
        self.assertEqual(gpu._pci("00000000:08:00.0"), "0000:08:00.0")
        self.assertEqual(gpu._pci("0000:0A:00.1"), "0000:0a:00.1")
        self.assertEqual(gpu._pci("08:00.0"), "0000:08:00.0")


class FdinfoTest(Base):
    def test_parse_amdgpu(self):
        info = gpu.parse_fdinfo(AMD_FDINFO)
        self.assertEqual((info["driver"], info["pdev"], info["client"]), ("amdgpu", "0000:03:00.0", "17"))
        self.assertEqual(info["vram"], 2 * 1024 * MIB)  # gtt (system memory) left out
        self.assertEqual(info["engines"], {"gfx": 1000000})

    def test_parse_xe_prefers_resident_and_skips_capacity(self):
        info = gpu.parse_fdinfo(XE_FDINFO)
        self.assertEqual(info["vram"], 1024 * MIB)
        self.assertEqual(info["engines"], {"rcs": 5000000000})

    def test_not_drm(self):
        self.assertIsNone(gpu.parse_fdinfo("pos:\t0\nflags:\t02\n"))

    def test_processes_from_fdinfo(self):
        self.tree.card(0, "0000:03:00.0", "0x1002", "0x747e", "amdgpu", AMD_FILES)
        self.tree.client(500, 9, AMD_FDINFO, comm="game")
        self.tree.client(500, 10, AMD_FDINFO, comm="game")         # same client id: once
        self.tree.client(501, 4, AMD_FDINFO.replace("17", "18").replace("2097152", "1048576"), comm="ollama")
        self.tree.client(502, 4, AMD_FDINFO.replace("0000:03:00.0", "0000:04:00.0"))   # another card
        self.assertEqual(gpu.processes(nvml=self.no_nvml), {500: 2048, 501: 1024})
        table = gpu.process_table(nvml=self.no_nvml)
        self.assertEqual([(r["name"], r["mib"], r["sm"]) for r in table],
                         [("game", 2048, None), ("ollama", 1024, None)])

    def test_intel_sampler(self):
        self.tree.client(600, 3, XE_FDINFO)
        s = gpu.Sampler("0000:00:02.0")
        self.assertIsNone(s(now=100.0))                 # the baseline
        self.tree.client(600, 3, XE_FDINFO.replace("5000000000", "5250000000"))
        self.assertEqual(s(now=101.0), 25)              # 0.25 s busy in 1 s


class EncoderTest(unittest.TestCase):
    NVIDIA_INFO = ("section=system_info\ndisplay_server|wayland\nsection=gpu_info\nvendor|nvidia\n"
                   "card_path|/dev/dri/card1\nsection=video_codecs\nh264\nh264_software\nhevc\nhevc_hdr\n"
                   "av1\nh264_vulkan\nsection=image_formats\njpeg\n")
    AMD_INFO = "section=gpu_info\nvendor|amd\nsection=video_codecs\nh264\nhevc\nhevc_hdr\nh264_software\n"
    CPU_INFO = "section=gpu_info\nvendor|intel\nsection=video_codecs\nh264_software\n"

    def test_from_gsr_info(self):
        self.assertEqual(gpu.parse_gsr_info(self.NVIDIA_INFO)["codecs"],
                         ["h264", "h264_software", "hevc", "hevc_hdr", "av1", "h264_vulkan"])
        nv = gpu.pick_encoder(self.NVIDIA_INFO, "nvidia")
        self.assertEqual((nv["encoder"], nv["api"], nv["hdr"]), ("gpu", "nvenc", True))
        amd = gpu.pick_encoder(self.AMD_INFO, "amd")
        self.assertEqual((amd["encoder"], amd["api"], amd["hdr"]), ("gpu", "vaapi", True))
        cpu = gpu.pick_encoder(self.CPU_INFO, "intel")
        self.assertEqual((cpu["encoder"], cpu["api"], cpu["hdr"]), ("cpu", "x264", False))

    def test_vulkan_only_is_not_hardware(self):
        info = "section=gpu_info\nvendor|amd\nsection=video_codecs\nh264_vulkan\nh264_software\n"
        self.assertEqual(gpu.pick_encoder(info, "amd")["encoder"], "cpu")

    def test_guess_without_gsr(self):
        self.assertEqual(gpu.pick_encoder("", "nvidia", nvml_ok=True)["api"], "nvenc")
        self.assertEqual(gpu.pick_encoder("", "nvidia", nvml_ok=False)["api"], "x264")   # nouveau
        self.assertEqual(gpu.pick_encoder("", "intel", render_node=True)["api"], "vaapi")
        self.assertEqual(gpu.pick_encoder("", "amd", render_node=False)["api"], "x264")
        self.assertEqual(gpu.pick_encoder("", "none")["encoder"], "cpu")


class CsvTest(unittest.TestCase):
    def test_stream_line(self):
        card = {"temp": 61, "vram_used": 3072, "vram_total": 16384, "power": 187.4, "fan": None}
        self.assertEqual(gpu._csv(card, 42), "42, 61, 3072, 16384, 187, N/A, display, other")
        self.assertEqual(gpu._csv(dict(card, temp=None, vram_used=None, vram_total=None), None),
                         "N/A, N/A, N/A, N/A, 187, N/A, display, other")
        self.assertTrue(gpu._csv(dict(card, vendor="nvidia"), 42, "offload").endswith(", offload, nvidia"))


class HybridTest(Base):
    """A laptop: the screens on an AMD APU, an NVIDIA offload card with no
    connectors that may be powered down (runtime D3)."""

    APU = {"gpu_busy_percent": "12\n", "mem_info_vram_used": str(400 * MIB),
           "mem_info_vram_total": str(512 * MIB), "hwmon/hwmon1/temp1_input": "50000\n"}

    def setUp(self):
        super().setUp()
        self.nv = self.tree.card(0, "0000:08:00.0", "0x10de", "0x1f9c", "nvidia", connectors=False)
        self.amd = self.tree.card(1, "0000:05:00.0", "0x1002", "0x164c", "amdgpu", self.APU)
        self.tree.write(os.path.join(self.tree.sys, "class", "drm", "card1-eDP-1", "status"), "connected\n")
        self.fake = FakeNvml()
        self.nvml = gpu.Nvml(lib=self.fake)
        self.saved_cache, gpu.VRAM_CACHE = gpu.VRAM_CACHE, os.path.join(self.tree.root, "vram.json")
        gpu._VRAM.clear()

    def tearDown(self):
        gpu.VRAM_CACHE = self.saved_cache
        gpu._VRAM.clear()
        super().tearDown()

    def runtime(self, status):
        self.tree.write(os.path.join(self.tree.sys, "devices", "pci0000:00", "0000:08:00.0", "power",
                                     "runtime_status"), status + "\n")

    def d3(self, on):
        self.tree.write(os.path.join(self.tree.proc, "driver", "nvidia", "gpus", "0000:08:00.0", "power"),
                        f"Runtime D3 status:          {'Enabled (fine-grained)' if on else 'Disabled by default'}\n")

    def test_display_and_offload(self):
        cards = gpu.gpus(self.nvml)
        self.assertEqual(gpu.primary(self.nvml)["vendor"], "nvidia")      # models still go there
        self.assertEqual(gpu.display_card(cards)["vendor"], "amd")
        self.assertEqual([g["vendor"] for g in gpu.offload_cards(cards)], ["nvidia"])

    def test_shown_card_follows_what_runs(self):
        self.assertEqual(gpu.shown_card(nvml=self.nvml)[1], "offload")    # the fake has processes
        self.fake.compute, self.fake.graphics = {}, {}
        self.fake.nvmlDeviceGetUtilizationRates = lambda _h, util: (setattr(obj(util), "gpu", 0), 0)[1]
        card, which = gpu.shown_card(nvml=self.nvml)
        self.assertEqual((card["vendor"], which), ("amd", "display"))

    def test_a_sleeping_card_is_not_asked(self):
        gpu.gpus(self.nvml)                                  # awake once: its size is remembered
        self.runtime("suspended")
        calls = []
        self.fake.nvmlDeviceGetCount_v2 = lambda count: calls.append(1) or 0
        cards = gpu.gpus(self.nvml)
        self.assertEqual(calls, [])
        nv = next(g for g in cards if g["vendor"] == "nvidia")
        self.assertEqual((nv["source"], nv["util"], nv["vram_used"]), ("asleep", 0, 0))
        self.assertEqual(nv["vram_total"], 24 * 1024)
        self.assertFalse(gpu.in_use(nv, self.nvml))
        self.assertEqual(gpu.processes(nv, nvml=self.nvml), {})
        self.assertEqual(gpu.shown_card(cards, self.nvml)[1], "display")

    def test_nvml_let_go_when_idle_and_able_to_sleep(self):
        idle = lambda _h, util: (setattr(obj(util), "gpu", 0), 0)[1]          # noqa: E731
        self.fake.nvmlDeviceGetUtilizationRates = idle
        self.fake.nvmlDeviceGetMemoryInfo = lambda _h, mem: (
            setattr(obj(mem), "total", 2048 * MIB), setattr(obj(mem), "used", MIB), 0)[2]
        shut = []
        self.fake.nvmlShutdown = lambda: shut.append(1) or 0
        gpu.gpus(self.nvml)
        self.assertEqual(shut, [])                           # D3 off: it never sleeps, keep NVML
        self.d3(True)
        gpu.gpus(self.nvml)
        self.assertEqual(shut, [1])
        self.assertIsNone(self.nvml.state)

    def test_may_sleep(self):
        self.assertFalse(gpu.may_sleep("0000:08:00.0"))
        self.d3(False)
        self.assertFalse(gpu.may_sleep("0000:08:00.0"))
        self.d3(True)
        self.assertTrue(gpu.may_sleep("0000:08:00.0"))


class LlmGpuCard(unittest.TestCase):
    """llm-gpu.py's card from gpu.py (card_info): any vendor, no card, an iGPU."""

    def setUp(self):
        self.lg = helpers.import_script("llm-gpu.py")

    def test_amd_card(self):
        card = {"name": "AMD Radeon RX 7800 XT", "vendor": "amd", "vram_used": 3072, "vram_total": 16384}
        info = self.lg.card_info(card, {7: 1024, 8: 2048}, {7: "llama-server"})
        self.assertEqual((info["name"], info["total"], info["used"]),
                         ("AMD Radeon RX 7800 XT", 16 * 2 ** 30, 3 * 2 ** 30))
        self.assertEqual([(p["pid"], p["name"]) for p in info["procs"]], [(8, "pid 8"), (7, "llama-server")])

    def test_no_card_or_igpu(self):
        self.assertIsNone(self.lg.card_info(None, {}))
        self.assertIsNone(self.lg.card_info({"name": "Intel", "vram_used": None, "vram_total": None}, {}))


if __name__ == "__main__":
    unittest.main()
