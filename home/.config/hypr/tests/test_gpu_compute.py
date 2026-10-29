"""gpu.py, the review's fixes: NVML's _v2 memory call (the "used" nvidia-smi
shows, without the driver's reserve), xe's busy cycles for the Intel load,
compute_only on AMD (ROCm clients: /dev/kfd) and elsewhere (nothing), the
stream hiding a card that gives no numbers (nouveau), and an integrated
GPU's carve-out never counting as card memory (railguard, llm-gpu.py,
welcome.py). Fake sysfs / proc trees and a fake NVML from test_gpu.py."""
import contextlib
import io
import os
import unittest
from unittest import mock

import helpers
import test_gpu as base

gpu = base.gpu
MIB = base.MIB


class FakeNvmlV2(base.FakeNvml):
    """A driver with nvmlDeviceGetMemoryInfo_v2: 512 MiB reserved."""

    def nvmlDeviceGetMemoryInfo_v2(self, _h, mem):
        m = base.obj(mem)
        if m.version != (gpu.ctypes.sizeof(gpu._MemoryV2) | (2 << 24)):
            return 2                                    # NVML_ERROR_INVALID_ARGUMENT
        m.total, m.reserved = 24 * 1024 * MIB, 512 * MIB
        m.used, m.free = 5 * 1024 * MIB + 512 * MIB, 18 * 1024 * MIB
        return 0


class NvmlMemory(unittest.TestCase):
    def test_v2_used_leaves_the_reserve_out(self):
        d = gpu.Nvml(FakeNvmlV2()).device(0)
        self.assertEqual((d["vram_used"], d["vram_total"]), (5632, 24576))

    def test_old_driver_falls_back_to_v1(self):
        d = gpu.Nvml(base.FakeNvml()).device(0)
        self.assertEqual((d["vram_used"], d["vram_total"]), (6144, 24576))


XE_CYCLES = """drm-driver:\txe
drm-pdev:\t0000:00:02.0
drm-client-id:\t9
drm-cycles-rcs:\t{used}
drm-total-cycles-rcs:\t{total}
drm-engine-capacity-rcs:\t1
"""

KFD_FDINFO = base.AMD_FDINFO.replace("drm-client-id:\t17", "drm-client-id:\t40")


class Fdinfo(base.Base):
    def test_xe_cycles_parsed(self):
        info = gpu.parse_fdinfo(XE_CYCLES.format(used=100, total=1000))
        self.assertEqual(info["cycles"], {"rcs": (100, 1000)})
        self.assertEqual(info["engines"], {})

    def test_xe_sampler_from_cycles(self):
        self.tree.client(700, 3, XE_CYCLES.format(used=1000, total=10000))
        s = gpu.Sampler("0000:00:02.0")
        self.assertIsNone(s(now=10.0))
        self.tree.client(700, 3, XE_CYCLES.format(used=4000, total=20000))
        self.assertEqual(s(now=11.0), 30)               # 3000 busy of 10000 cycles

    def _kfd(self, pid):
        os.symlink("/dev/kfd", os.path.join(self.tree.proc, str(pid), "fd", "99"))

    def test_amd_compute_only_keeps_rocm_clients(self):
        self.tree.card(0, "0000:03:00.0", "0x1002", "0x747e", "amdgpu", base.AMD_FILES)
        self.tree.client(500, 9, base.AMD_FDINFO, comm="firefox")
        self.tree.client(501, 4, KFD_FDINFO, comm="ollama")
        self._kfd(501)
        nv = gpu.Nvml(lib=object())
        self.assertEqual(gpu.processes(nvml=nv), {500: 2048, 501: 2048})
        self.assertEqual(gpu.processes(compute_only=True, nvml=nv), {501: 2048})

    def test_intel_compute_only_is_nothing(self):
        self.tree.card(0, "0000:00:02.0", "0x8086", "0x56a0", "i915", {"lmem_total_bytes": "8589934592\n"})
        self.tree.client(600, 3, base.XE_FDINFO)
        nv = gpu.Nvml(lib=object())
        self.assertEqual(gpu.processes(compute_only=True, nvml=nv), {})


class Stream(base.Base):
    def _stream(self):
        out = io.StringIO()
        with mock.patch.object(gpu, "NVML", self.no_nvml), contextlib.redirect_stdout(out):
            rc = gpu.stream(0)
        return rc, out.getvalue()

    def test_card_without_numbers_hides_the_pill(self):
        self.tree.card(0, "0000:01:00.0", "0x10de", "0x2684", "nouveau")
        self.assertEqual(self._stream(), (3, "none\n"))

    def test_no_card(self):
        self.assertEqual(self._stream(), (3, "none\n"))


APU = {"vendor": "amd", "name": "AMD Radeon 780M", "source": "sysfs", "index": None, "pci": "0000:c5:00.0",
       "discrete": False, "vram_used": 500, "vram_total": 512}


class IntegratedCarveOut(unittest.TestCase):
    def test_railguard_does_not_watch_an_apu(self):
        rg = helpers.import_script("railguard.py")

        class Fake:
            def primary(self):
                return dict(APU)
        saved, rg.GPU = rg.GPU, Fake()
        try:
            self.assertIsNone(rg.gpu_card())
            self.assertIsNone(rg.gpu_memory())
        finally:
            rg.GPU = saved

    def test_llm_gpu_says_unknown_for_an_apu(self):
        lg = helpers.import_script("llm-gpu.py")
        self.assertIsNone(lg.card_info(dict(APU), {1: 100}))
        self.assertIsNotNone(lg.card_info(dict(APU, discrete=True, vram_total=16384), {}))

    def test_welcome_advice_uses_ram_for_an_apu(self):
        w = helpers.import_script("welcome.py")
        self.assertIn("RAM (32 GB)", w.model_advice(dict(APU), 32 * 2 ** 30))


if __name__ == "__main__":
    unittest.main()
