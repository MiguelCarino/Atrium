"""railguard.py's VRAM watch on gpu.py (in-process, any vendor): the card and
its processes come from a fake gpu module, never the real card; no card (or
one that reports no memory) turns the watch off; a full card ends the
biggest non-game process and spares a game. Nothing is signalled: the
ending, the history and the notification are stubbed."""
import json
import os
import tempfile
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
        self.state = {"psi": 0, "vram": 99, "vram_n": 9, "quiet": 0.0}  # full for long enough already
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


USER = "/user.slice/user-1000.slice/user@1000.service"
CERBERUS = USER + "/app.slice/cerberus.service"
LMS_SCOPE = USER + "/app.slice/cerberus-lmstudio.scope"     # Cerberus' fallback for LM Studio's daemon
SESSION = USER + "/cerberus-sessions.slice/run-s1-c1.scope"
APP = USER + "/app.slice/app-python.scope"
AGENT = USER + "/agents.slice/run-p1-i1.scope"
FULL, CLEAR, HARD = 23500, 22000, 23900       # of 24000: 97.9 %, 91.7 %, 99.6 %


def at(pid, name, cgroup, weight=1.0, game=False):
    return {"pid": pid, "name": name, "cgroup": cgroup, "mem": 0, "ticks": 0, "start": 1,
            "weight": weight, "game": game}


class VramEpisode(unittest.TestCase):
    """The card full for a while, sample by sample (3 s apart on a fake
    clock): who grew since it crossed the line, the ask of a managed engine
    (the pressure file, the grace counted across samples), the hard line."""

    INFOS = {10: at(10, "llama-server", CERBERUS), 11: at(11, "python3", APP),
             12: at(12, "llama-server", AGENT, weight=rg.AGENT_WEIGHT),
             13: at(13, "Game.exe", APP, game=True), 14: at(14, "llama-server", LMS_SCOPE)}

    def setUp(self):
        rg.load_settings()
        self.cfg = mock.patch.dict(rg.CFG, {"spare_games": True, "never_kill": [], "kill_first": [],
                                            "vram_pct": 97.0, "vram_s": 12, "notify": False,
                                            "managed_units": ["cerberus-lmstudio.scope", "cerberus.service",
                                                              "lmstudio.service"],
                                            "managed_grace_s": 20, "vram_hard_pct": 99.5})
        self.cfg.start()
        self.clock = [1_800_000_000.0]
        self.state = {"psi": 0, "vram": 0, "vram_n": 0, "quiet": 0.0}
        self.patches = [mock.patch.object(rg, "term_then_kill"), mock.patch.object(rg, "record"),
                        mock.patch.object(rg, "notify"),
                        mock.patch.object(rg.time, "time", lambda: self.clock[0]),
                        mock.patch.object(rg.time, "sleep", side_effect=AssertionError("check_vram slept")),
                        mock.patch.object(rg, "proc_info", side_effect=lambda pid: self.INFOS.get(pid)),
                        mock.patch.object(rg, "log")]
        self.kill, self.record, self.notify = (p.start() for p in self.patches[:3])
        for p in self.patches[3:]:
            p.start()
        rg.clear_pressure()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.cfg.stop()
        rg.GPU = None
        rg.clear_pressure()

    def sample(self, used, procs, **card):
        rg.GPU = FakeGpu(dict(NVIDIA, vram_used=used, **card), procs)
        rg.check_vram(self.state, 3)
        self.clock[0] += 3

    def kinds(self):
        return [c.args[0] for c in self.record.call_args_list]

    def pressure(self):
        try:
            with open(rg.PRESSURE_FILE) as fh:
                return json.load(fh)
        except OSError:
            return None

    def ended(self):
        return [c.args[0]["name"] + f"/{c.args[0]['pid']}" for c in self.kill.call_args_list]

    def grower_goes(self, engine):
        for grown in (2000, 2500, 3000, 3500):
            self.sample(FULL, {engine: 18000, 11: grown})
        self.assertEqual(self.ended(), ["python3/11"])
        self.assertEqual(self.kinds(), ["vram"])
        self.assertIn("grew 1.5 GB", self.record.call_args.args[2])
        self.assertIsNone(self.pressure())       # nobody was asked

    def test_a_grower_goes_not_the_steady_managed_engine(self):
        self.grower_goes(10)

    def test_a_grower_goes_not_the_steady_agent_engine(self):
        self.grower_goes(12)                     # x2 weight and bigger, but steady

    def test_a_steady_managed_engine_is_asked_then_ended_after_the_grace(self):
        for _ in range(4):                       # 12 s full; nothing grew (the desktop did)
            self.sample(FULL, {10: 18000})
        self.kill.assert_not_called()
        self.assertEqual(self.kinds(), ["vram-asked"])
        asked = self.record.call_args
        self.assertEqual(asked.args[1]["name"], "llama-server")
        p = self.pressure()
        self.assertEqual((p["v"], p["resource"], p["used_mib"], p["total_mib"]), (1, "vram", FULL, 24000))
        self.assertEqual(p["target_mib"], int(24000 * 0.97) - rg.PRESSURE_MARGIN_MIB)
        self.assertEqual(p["managed_units"], ["cerberus-lmstudio.scope", "cerberus.service",
                                              "lmstudio.service"])
        self.assertEqual(p["act_at"] - p["time"], 20)
        for _ in range(6):                       # 18 s of the 20: it waits
            self.sample(FULL, {10: 18000})
        self.kill.assert_not_called()
        self.assertIsNotNone(self.pressure())
        self.sample(FULL, {10: 18000})           # 21 s: still full
        self.assertEqual(self.ended(), ["llama-server/10"])
        self.assertEqual(self.kinds(), ["vram-asked", "vram"])
        self.assertTrue(self.record.call_args.args[2].endswith("; asked first"))
        self.assertIn("did not", self.notify.call_args.args[1])
        self.assertIsNone(self.pressure())       # deleted after it acted
        self.assertIsNone(self.state["ask"])

    def test_vram_shed_when_the_card_clears_within_the_grace(self):
        for _ in range(4):
            self.sample(FULL, {10: 18000})
        self.assertEqual(self.kinds(), ["vram-asked"])
        self.sample(FULL, {10: 18000})
        self.sample(CLEAR, {10: 16500})          # Cerberus unloaded something
        self.kill.assert_not_called()
        self.assertEqual(self.kinds(), ["vram-asked", "vram-shed"])
        self.assertIn("Cerberus freed", self.notify.call_args.args[0])
        self.assertIsNone(self.pressure())
        self.assertIsNone(self.state["ask"])

    def test_after_a_shed_the_next_fill_is_asked_again(self):
        # the engine did what it was asked; its next turn reloads within 2 min
        for _ in range(4):
            self.sample(FULL, {10: 18000})
        self.sample(CLEAR, {10: 16500})          # shed
        self.assertNotIn("asked_at", self.state)
        for _ in range(4):                       # full again 3 s later: asked again, nothing ended
            self.sample(FULL, {10: 18000})
        self.kill.assert_not_called()
        self.assertEqual(self.kinds(), ["vram-asked", "vram-shed", "vram-asked"])
        self.assertIsNotNone(self.pressure())

    def test_after_an_ignored_ask_the_next_fill_is_not_asked_nor_called_asked_first(self):
        for _ in range(11):                      # asked, ignored, ended
            self.sample(FULL, {10: 18000, 11: 1000})
        self.assertEqual(self.kinds(), ["vram-asked", "vram"])
        self.assertTrue(self.record.call_args.args[2].endswith("; asked first"))
        self.clock[0] += rg.COOLDOWN * 3         # past the quiet after the ending
        self.sample(CLEAR, {14: 16000, 11: 1000})
        for _ in range(4):                       # a minute after the ask: it acts, no second ask
            self.sample(FULL, {14: 18000, 11: 1000})
        self.assertEqual(self.kinds(), ["vram-asked", "vram", "vram"])
        self.assertEqual(self.ended()[-1], "llama-server/14")
        self.assertNotIn("asked first", self.record.call_args.args[2])
        self.assertNotIn("did not", self.notify.call_args.args[1])
        self.assertIsNone(self.pressure())

    def test_an_engine_that_keeps_refilling_the_card_is_asked_at_most_three_times(self):
        for _round in range(rg.SHED_LIMIT):
            for _ in range(4):
                self.sample(FULL, {10: 18000})
            self.sample(CLEAR, {10: 16500})
            self.clock[0] += 60
        self.assertEqual(self.kinds(), ["vram-asked", "vram-shed"] * rg.SHED_LIMIT)
        for _ in range(4):                       # the fourth fill in ten minutes: not asked
            self.sample(FULL, {10: 18000})
        self.assertEqual(self.kinds()[-1], "vram")
        self.assertEqual(self.ended(), ["llama-server/10"])
        self.assertNotIn("asked first", self.record.call_args.args[2])
        self.assertEqual(self.state["sheds"], [])      # counted anew after the ending

    def test_cerberus_lmstudio_scope_is_asked_first(self):
        for _ in range(4):
            self.sample(FULL, {14: 18000})
        self.kill.assert_not_called()
        self.assertEqual(self.kinds(), ["vram-asked"])
        self.assertEqual(rg.engine_label("cerberus-lmstudio.scope"), "LM Studio")

    def test_the_hard_line_acts_at_once(self):
        for _ in range(4):
            self.sample(HARD, {10: 18000})
        self.assertEqual(self.ended(), ["llama-server/10"])
        self.assertEqual(self.kinds(), ["vram"])
        self.assertIsNone(self.pressure())

    def test_the_hard_line_counts_against_what_used_can_reach(self):
        # the RTX 4090: 24564 MiB, 455 kept by the driver, so "used" tops out
        # at 24109 (98.1 % of the total). 99.5 % of that is 23988: reachable.
        card = {"vram_total": 24564, "vram_reserved": 455}
        for _ in range(4):
            self.sample(24000, {10: 18000}, **card)
        self.assertEqual(self.ended(), ["llama-server/10"])
        self.assertEqual(self.kinds(), ["vram"])     # nobody asked: no waiting with the card at its top
        self.assertIsNone(self.pressure())

    def test_without_a_reserve_the_same_reading_is_asked(self):
        # an old driver ("used" counts the reserve): 24000 of 24564 is 97.7 %, asked first
        for _ in range(4):
            self.sample(24000, {10: 18000}, vram_total=24564)
        self.kill.assert_not_called()
        self.assertEqual(self.kinds(), ["vram-asked"])

    def test_the_hard_line_is_full_even_above_an_unreachable_vram_pct(self):
        rg.CFG["vram_pct"] = 99.0                # 24318 MiB: "used" never gets there
        card = {"vram_total": 24564, "vram_reserved": 455}
        for _ in range(4):
            self.sample(24050, {11: 20000}, **card)
        self.assertEqual(self.ended(), ["python3/11"])

    def test_growth_that_took_the_card_over_counts(self):
        # a busy managed model steady at 2 GB; a hog that grew to the line
        # before it crossed (readings under the line, within 10 points)
        for used, grown in ((21000, 19000), (22000, 20000), (23000, 21000)):   # 87.5 .. 95.8 %
            self.sample(used, {10: 2000, 11: grown})
        for _ in range(4):
            self.sample(FULL, {10: 2000, 11: 22500})
        self.assertEqual(self.ended(), ["python3/11"])
        self.assertEqual(self.kinds(), ["vram"])     # ended at once: nobody was asked
        self.assertIn("grew 3.4 GB", self.record.call_args.args[2])   # from the lowest of the last 30 s
        self.assertIsNone(self.pressure())

    def test_readings_older_than_the_window_are_not_the_baseline(self):
        self.sample(21000, {10: 2000, 11: 10000})    # a minute ago: the hog loaded then
        self.clock[0] += 60
        self.sample(21500, {10: 2000, 11: 19500})
        for _ in range(4):                           # steady since: not a grower
            self.sample(FULL, {10: 2000, 11: 19500})
        self.kill.assert_not_called()
        self.assertEqual(self.kinds(), ["vram-asked"])

    def test_far_below_no_readings_are_taken(self):
        self.sample(10000, {10: 2000, 11: 500})
        self.assertEqual(self.state.get("seen"), [])
        self.assertEqual(rg.GPU.asked, [])           # the process list is not read far from the line
        for _ in range(4):                           # one jump over: the baseline is the crossing
            self.sample(FULL, {10: 2000, 11: 19500})
        self.assertEqual(self.kinds(), ["vram-asked"])

    def test_the_hard_line_during_the_grace(self):
        for _ in range(4):
            self.sample(FULL, {10: 18000})
        self.sample(HARD, {10: 18000})
        self.assertEqual(self.ended(), ["llama-server/10"])
        self.assertIsNone(self.pressure())

    def test_an_unmanaged_engine_in_an_agents_scope_is_ended_as_before(self):
        for _ in range(4):
            self.sample(FULL, {12: 18000})
        self.assertEqual(self.ended(), ["llama-server/12"])
        self.assertEqual(self.kinds(), ["vram"])
        self.assertIsNone(self.pressure())
        self.assertNotIn("asked", self.record.call_args.args[2])

    def test_a_managed_grower_is_asked_first(self):
        for grown in (16000, 17000, 18000, 19000):
            self.sample(FULL, {10: grown})
        self.kill.assert_not_called()
        self.assertEqual(self.kinds(), ["vram-asked"])
        for _ in range(7):
            self.sample(FULL, {10: 19000})
        self.assertEqual(self.ended(), ["llama-server/10"])
        self.assertIn("grew", self.record.call_args.args[2])

    def test_after_an_ask_the_engine_counts_half(self):
        # 18 GB managed x0.5 = 9 < 10 GB unmanaged, steady both: the other one goes
        for _ in range(11):
            self.sample(FULL, {10: 18000, 11: 10000})
        self.assertEqual(self.ended(), ["python3/11"])
        self.assertEqual(self.kinds(), ["vram-asked", "vram"])

    def test_a_growing_game_is_still_spared(self):
        for grown in (6000, 7000, 8000, 9000):
            self.sample(FULL, {10: 14000, 13: grown})
        self.kill.assert_not_called()
        self.assertEqual(self.kinds(), ["vram-asked"])

    def test_the_watch_going_off_drops_the_ask(self):
        for _ in range(4):
            self.sample(FULL, {10: 18000})
        self.assertIsNotNone(self.pressure())
        rg.drop_ask(self.state)
        self.assertIsNone(self.pressure())
        self.assertEqual(self.kinds(), ["vram-asked"])


class NoWaitingKill(unittest.TestCase):
    """term_then_kill with the daemon's state sends SIGTERM and leaves the
    SIGKILL to reap(), which sends it once due and only to that process."""

    def test_sigkill_is_due_later_and_only_to_the_same_process(self):
        p = at(4242, "runaway", APP)
        state = {}
        with mock.patch.object(rg.os, "kill") as kill, mock.patch.object(rg.time, "sleep") as sleep, \
                mock.patch.object(rg, "log"):
            self.assertTrue(rg.term_then_kill(p, state))
            sleep.assert_not_called()
            kill.assert_called_once_with(4242, rg.signal.SIGTERM)
            due = state["reap"][0]["at"]
            with mock.patch.object(rg, "still_there", return_value=True):
                rg.reap(state, due - 1)
                self.assertEqual(kill.call_count, 1)        # not yet
                rg.reap(state, due)
            kill.assert_called_with(4242, rg.signal.SIGKILL)
            self.assertEqual(state["reap"], [])
            rg.term_then_kill(p, state)
            with mock.patch.object(rg, "still_there", return_value=False):
                rg.reap(state, due + 99)                   # it ended, or its pid is someone else's
            self.assertNotEqual(kill.call_args.args[1], rg.signal.SIGKILL)
            self.assertEqual(state["reap"], [])

    def test_still_there_checks_the_start_time(self):
        with open(f"/proc/{os.getpid()}/stat") as fh:
            stat = fh.read()
        start = rg.proc_start(stat[stat.rindex(")") + 2:].split())
        self.assertTrue(rg.still_there(os.getpid(), start))
        self.assertFalse(rg.still_there(os.getpid(), start + 1))


class LmStudioInAnAgentScope(unittest.TestCase):
    def setUp(self):
        self.proc = tempfile.mkdtemp(dir=helpers.SCRATCH)

    def add(self, pid, name, cgroup):
        d = os.path.join(self.proc, str(pid))
        os.makedirs(d)
        for f, text in (("comm", name + "\n"), ("cgroup", f"0::{cgroup}\n")):
            with open(os.path.join(d, f), "w") as fh:
                fh.write(text)

    def test_a_cerberus_session_is_an_agents_command(self):
        self.add(300, "llmster", SESSION)
        state = {}
        with mock.patch.object(rg, "notify") as note, mock.patch.object(rg, "kill") as kill:
            rg.check_lms_scopes(state, self.proc)
        self.assertEqual(note.call_count, 1)
        self.assertIn("an agent's command", note.call_args.args[0])
        self.assertIn("run-s1-c1.scope", note.call_args.args[1])
        kill.assert_not_called()

    def test_warns_once_per_daemon_and_ends_nothing(self):
        self.add(100, "llmster", AGENT)
        self.add(101, "llama-server", AGENT)
        self.add(102, "llmster", USER + "/app.slice/lmstudio.service")     # where it belongs
        self.add(103, "node", AGENT)
        state = {}
        with mock.patch.object(rg, "notify") as note, mock.patch.object(rg, "kill") as kill:
            rg.check_lms_scopes(state, self.proc)
            rg.check_lms_scopes(state, self.proc)
            self.assertEqual(note.call_count, 1)
            self.assertIn("lms daemon down", note.call_args.args[1])
            self.assertIn("pid 100", note.call_args.args[1])
            self.assertIn("run-p1-i1.scope", note.call_args.args[1])
            self.add(200, "llmster", USER + "/heavy.slice/run-9.scope")    # another daemon
            rg.check_lms_scopes(state, self.proc)
            self.assertEqual(note.call_count, 2)
            self.assertIn("heavy build", note.call_args.args[0])
        kill.assert_not_called()


if __name__ == "__main__":
    unittest.main()
