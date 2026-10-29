"""Whatever card is in the box: the PiP recorder's encoder, voice typing's
free-VRAM check, the About page's numbers for AMD / Intel cards, the LLM
bench's card memory, and window-look's fallback for a fourth screen and the
main modifier -- the pure parts, with made-up cards (gpu.py's shape)."""
import unittest

import helpers

pip = helpers.import_script("pip.py")
voice = helpers.import_script("voice.py")
sysinfo = helpers.import_script("system-info.py")
bench = helpers.import_script("llm-bench.py")
look = helpers.import_script("window-look.py")

NVIDIA = {"vendor": "nvidia", "pci": "0000:08:00.0", "discrete": True, "vram_used": 2000,
          "vram_total": 24564, "util": 7, "temp": 43, "power": 61.4}
AMD = {"vendor": "amd", "pci": "0000:03:00.0", "discrete": True, "vram_used": 1024,
       "vram_total": 16368, "util": 12, "temp": 50, "power": None}
INTEL_IGPU = {"vendor": "intel", "pci": "0000:00:02.0", "discrete": False, "vram_used": None,
              "vram_total": None, "util": None, "temp": None, "power": None}


class Pip(unittest.TestCase):
    def test_cpu_encoder_is_asked_for(self):
        argv = pip.gsr_argv((0, 0, 640, 360), 30, "cpu")
        self.assertEqual(argv[argv.index("-encoder") + 1], "cpu")
        self.assertEqual(argv[-2:], ["-o", "/dev/stdout"])

    def test_gpu_encoder_is_gsr_default(self):
        self.assertNotIn("-encoder", pip.gsr_argv((0, 0, 640, 360), 30, "gpu"))
        self.assertNotIn("-encoder", pip.gsr_argv((0, 0, 640, 360), 30))


class Voice(unittest.TestCase):
    def test_free_memory_only_of_a_cuda_card(self):
        self.assertEqual(voice.free_mb_of(NVIDIA), 22564)
        self.assertIsNone(voice.free_mb_of(AMD))
        self.assertIsNone(voice.free_mb_of(INTEL_IGPU))
        self.assertIsNone(voice.free_mb_of(None))
        self.assertIsNone(voice.free_mb_of(dict(NVIDIA, vram_used=None)))

    def test_no_card_message_names_no_maker(self):
        settings = dict(voice.DEFAULTS, device="auto")
        device, _model, _ct, why = voice.plan_engine(settings, None, False)
        self.assertEqual(device, "cpu")
        self.assertNotIn("NVIDIA", why)
        self.assertNotIn("nvidia-smi", why)
        device, *_rest, why = voice.plan_engine(dict(settings, device="cuda"), None, False)
        self.assertIsNone(device)
        self.assertIn("CUDA", why)


class AboutPage(unittest.TestCase):
    def test_numbers_line(self):
        self.assertEqual(sysinfo.gpu_numbers(AMD), "busy 12 %  ·  VRAM in use 1024 of 16368 MiB  ·  50 °C")
        self.assertEqual(sysinfo.gpu_numbers(NVIDIA).split("  ·  ")[-1], "61 W")
        self.assertEqual(sysinfo.gpu_numbers(INTEL_IGPU), "shares the RAM (integrated)")
        self.assertEqual(sysinfo.gpu_numbers(None), "")
        apu = {"vendor": "amd", "discrete": False, "vram_used": 300, "vram_total": 512, "util": 3,
               "temp": None, "power": None}
        self.assertEqual(sysinfo.gpu_numbers(apu), "busy 3 %  ·  shares the RAM (integrated)")

    def test_card_for_lspci_bus(self):
        cards = [NVIDIA, AMD, INTEL_IGPU]
        self.assertIs(sysinfo.card_for_bus(cards, "03:00.0"), AMD)
        self.assertIs(sysinfo.card_for_bus(cards, "00:02.0"), INTEL_IGPU)
        self.assertIsNone(sysinfo.card_for_bus(cards, "05:00.0"))


class Bench(unittest.TestCase):
    def test_card_memory(self):
        self.assertEqual(bench.card_memory(NVIDIA), (2000 * 2**20, 24564 * 2**20))
        self.assertEqual(bench.card_memory(INTEL_IGPU), (0, 0))
        self.assertEqual(bench.card_memory(None), (0, 0))
        self.assertEqual(bench.card_memory({"vendor": "amd", "vram_used": 200, "vram_total": 512,
                                            "discrete": False}), (0, 0))


class WindowLook(unittest.TestCase):
    def test_slots_follow_lua_workspaces(self):
        self.assertEqual([look.slot(n) for n in (2, 3, 4, 5, 7)], [4, 6, 7, 8, 10])
        self.assertEqual([look.last_workspace(n) for n in (0, 1, 3, 4, 6, 9)], [6, 6, 6, 7, 9, 10])

    def test_generated_pins(self):
        self.assertEqual(look.generated_pins(["A", "B", "C"]), [])
        self.assertEqual(look.generated_pins(["A", "B", "C", "D"]),
                         [{"workspace": "7", "monitor": "D", "default": True, "persistent": True}])
        self.assertEqual([p["workspace"] for p in look.generated_pins(list("ABCDEFGHIJ"))],
                         ["7", "8", "9", "10"])        # the 0 key is the last one

    def test_parse_reads_the_loop(self):
        text = ('pin("1", P, true)\npin("4", second or P, second ~= nil)\n'
                'for n = 4, #SCREENS do\n    local ws = W.slot(n)\n'
                '    if ws <= W.last(SCREENS) then pin(tostring(ws), SCREENS[n], true) end\nend\n')
        rules = look.parse_workspace_rules(text, "A", ["A", "B", "C", "D"])
        self.assertEqual([(r["workspace"], r["monitor"], r["default"]) for r in rules],
                         [("1", "A", True), ("4", "B", True), ("7", "D", True)])
        without = look.parse_workspace_rules('pin("1", P, true)\n', "A", ["A", "B", "C", "D"])
        self.assertEqual([r["workspace"] for r in without], ["1"])

    def test_main_mod(self):
        self.assertEqual(look.pick_main_mod("super"), "SUPER")
        self.assertEqual(look.pick_main_mod("ALT"), "ALT")
        self.assertEqual(look.pick_main_mod("HYPER"), "ALT")
        self.assertEqual(look.pick_main_mod(None), "ALT")
        self.assertIn(look.main_mod(), ("ALT", "SUPER"))


if __name__ == "__main__":
    unittest.main()
