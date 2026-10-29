"""railguard.py's VRAM watch on gpu.py (in-process, any vendor): the card and
its processes come from a fake gpu module, never the real card; no card (or
one that reports no memory) turns the watch off; a full card ends the
biggest non-game process and spares a game. Nothing is signalled: the
ending, the history and the notification are stubbed."""
import unittest
from unittest import mock

import helpers

rg = helpers.import_script("railguard.py")

NVIDIA = {"vendor": "nvidia", "name": "Test Card", "source": "nvml", "index": 0, "pci": "0000:08:00.0",
          "vram_used": 23800, "vram_total": 24000}
IGPU = {"vendor": "intel", "name": "Intel iGPU", "source": "sysfs", "index": None, "pci": "0000:00:02.0",
        "vram_used": None, "vram_total": None}


class FakeGpu:
    def __init__(self, card, procs=None):
        self.card, self.procs, self.asked = card, procs or {}, []

    def primary(self):
        return self.card

    def processes(self, card, compute_only=False):
        self.asked.append((card["pci"], compute_only))
        return dict(self.procs)


def proc(pid, name, game=False):
    return {"pid": pid, "name": name, "cgroup": "/user.slice/user@1000.service/app.slice/x.scope",
            "mem": 0, "ticks": 0, "weight": 1.0, "game": game}


class GpuSource(unittest.TestCase):
    def tearDown(self):
        rg.GPU = None

    def test_card_memory_and_processes(self):
        rg.GPU = FakeGpu(NVIDIA, {10: 9000})
        self.assertEqual(rg.gpu_memory(), (23800, 24000))
        self.assertEqual(rg.gpu_processes(), {10: 9000})
        self.assertEqual(rg.GPU.asked, [("0000:08:00.0", True)])     # compute only on NVIDIA

    def test_no_card_or_no_memory_is_off(self):
        for card in (None, IGPU):
            rg.GPU = FakeGpu(card, {10: 9000})
            self.assertIsNone(rg.gpu_card())
            self.assertIsNone(rg.gpu_memory())
            self.assertEqual(rg.gpu_processes(), {})

    def test_broken_gpu_module_is_off(self):
        class Broken:
            def primary(self):
                raise RuntimeError("driver went away")
        rg.GPU = Broken()
        with mock.patch.object(rg, "log") as log:
            self.assertIsNone(rg.gpu_memory())
        self.assertIn("driver went away", log.call_args.args[0])

    def test_no_nvidia_smi_is_forked(self):
        rg.GPU = FakeGpu(NVIDIA, {10: 9000})
        with mock.patch.object(rg.subprocess, "run") as run, mock.patch.object(rg.subprocess, "Popen") as popen:
            rg.gpu_memory()
            rg.gpu_processes()
        run.assert_not_called()
        popen.assert_not_called()

    def test_daemon_logs_why_vram_is_not_watched(self):
        rg.GPU = FakeGpu(None)
        said = []
        with mock.patch.object(rg, "log", said.append), \
                mock.patch.object(rg.time, "sleep", side_effect=KeyboardInterrupt), \
                mock.patch.object(rg, "load_settings"):
            with self.assertRaises(KeyboardInterrupt):
                rg.daemon()
        self.assertIn("VRAM not watched", said[0])


class CheckVram(unittest.TestCase):
    def setUp(self):
        rg.load_settings()
        # The defaults, whatever another test left in the scratch settings file.
        self.cfg = mock.patch.dict(rg.CFG, {"spare_games": True, "never_kill": [], "kill_first": [],
                                            "vram_pct": 97.0, "vram_s": 12, "notify": False})
        self.cfg.start()
        self.state = {"psi": 0, "vram": 99, "quiet": 0.0}      # full for long enough already
        self.patches = [mock.patch.object(rg, "term_then_kill"), mock.patch.object(rg, "record"),
                        mock.patch.object(rg, "notify")]
        self.kill, self.record, self.notify = (p.start() for p in self.patches)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.cfg.stop()
        rg.GPU = None

    def run_with(self, procs, infos):
        rg.GPU = FakeGpu(NVIDIA, procs)
        with mock.patch.object(rg, "proc_info", side_effect=lambda pid: infos.get(pid)):
            rg.check_vram(self.state)

    def test_ends_the_biggest_other_process(self):
        self.run_with({10: 9000, 11: 2000, 12: 12000},
                      {10: proc(10, "llama-server"), 11: proc(11, "python3"), 12: proc(12, "Game.exe", game=True)})
        self.kill.assert_called_once()
        self.assertEqual(self.kill.call_args.args[0]["name"], "llama-server")
        self.assertEqual(self.record.call_args.args[0], "vram")

    def test_a_game_alone_is_only_warned(self):
        self.run_with({12: 12000}, {12: proc(12, "Game.exe", game=True)})
        self.kill.assert_not_called()
        self.assertEqual(self.record.call_args.args[0], "game-vram")

    def test_below_the_line_does_nothing(self):
        rg.GPU = FakeGpu(dict(NVIDIA, vram_used=1000), {10: 900})
        rg.check_vram(self.state)
        self.assertEqual(self.state["vram"], 0)
        self.kill.assert_not_called()


if __name__ == "__main__":
    unittest.main()
