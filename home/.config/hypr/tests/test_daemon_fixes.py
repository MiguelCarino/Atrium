"""The background daemons' quieter, leaner ways (2026-10 fixes):

  * llm-limits.py's idle reaper: reap_decision, tcp_clients
  * desktop-memory.py: collect no longer embeds; embed_hourly (desktop-index's
    hourly run) starts LM Studio only now and then
  * brief.py: brief.timer's drop-in (timer_dropin) from the settings
  * timers.py: the alarm loop's argv never pastes a sound path into shell text
  * voice.py: the bar's sleep (bar_wait) and the inotify names (watch_names)

Hermetic: scratch stores, every LM Studio / systemctl call stubbed."""
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import helpers

gpu = helpers.import_script("llm-gpu.py")
limits = gpu.llm_models._limits_module()
dm = helpers.import_script("desktop-memory.py")
brief = helpers.import_script("brief.py")
timers = helpers.import_script("timers.py", "timers")
voice = helpers.import_script("voice.py")


class Reaper(unittest.TestCase):
    def test_busy_while_a_model_is_loaded(self):
        self.assertEqual(limits.reap_decision(["nomic"], 0, 100.0, 5000.0), ("busy", None))

    def test_busy_while_a_client_is_connected(self):
        self.assertEqual(limits.reap_decision([], 1, 100.0, 5000.0), ("busy", None))

    def test_unknown_when_the_api_is_silent(self):
        self.assertEqual(limits.reap_decision(None, 0, 100.0, 5000.0), ("unknown", None))

    def test_idle_clock_starts_then_stops(self):
        self.assertEqual(limits.reap_decision([], 0, None, 1000.0, 900), ("wait", 1000.0))
        self.assertEqual(limits.reap_decision([], 0, 1000.0, 1899.0, 900), ("wait", 1000.0))
        self.assertEqual(limits.reap_decision([], 0, 1000.0, 1900.0, 900), ("stop", 1000.0))

    def test_tcp_clients(self):
        header = "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid\n"
        tcp = header + (
            "   0: 0100007F:04D2 00000000:0000 0A 00000000:00000000 00:00000000 00000000  1000\n"   # listen 1234
            "   1: 0100007F:04D2 0100007F:D431 01 00000000:00000000 00:00000000 00000000  1000\n"   # client in
            "   2: 0100007F:D431 0100007F:04D2 01 00000000:00000000 00:00000000 00000000  1000\n"   # its other end
            "   3: 0100007F:A1AF 0100007F:9999 01 00000000:00000000 00:00000000 00000000  1000\n")  # 41391: not ours
        self.assertEqual(limits.tcp_clients((1234,), [tcp]), 1)
        self.assertEqual(limits.tcp_clients((41343,), [tcp]), 0)

    def test_reap_leaves_an_outside_daemon_alone(self):
        with mock.patch.object(limits, "unit_installed", return_value=True), \
                mock.patch.object(limits, "unit_active", return_value=True), \
                mock.patch.object(limits, "lm_procs", return_value=[{"pid": 1, "comm": "llmster",
                                                                      "cgroup": "/app.slice/x.scope"}]), \
                mock.patch.object(limits, "_systemctl") as ctl:
            self.assertIn("outside", limits.reap())
            ctl.assert_not_called()

    def test_reap_stops_after_the_idle_time(self):
        inside = [{"pid": 1, "comm": "llmster", "cgroup": "/app.slice/lmstudio.service"}]
        with mock.patch.object(limits, "unit_installed", return_value=True), \
                mock.patch.object(limits, "unit_active", return_value=True), \
                mock.patch.object(limits, "lm_procs", return_value=inside), \
                mock.patch.object(limits, "loaded_models", return_value=[]), \
                mock.patch.object(limits, "_proc_net", return_value=[]), \
                mock.patch.object(limits, "_systemctl",
                                  return_value=subprocess.CompletedProcess([], 0, "", "")) as ctl:
            limits._save_idle_since(None)
            self.assertTrue(limits.REAP_STATE.startswith(helpers.SCRATCH))
            self.assertIn("idle 0 of 15", limits.reap(now=1000.0))
            ctl.assert_not_called()
            self.assertIn("stopped", limits.reap(now=1000.0 + limits.REAP_IDLE_S))
            ctl.assert_called_once()
            self.assertIn("stop", ctl.call_args[0])

    def test_reap_with_the_http_server_off_counts_llama_servers(self):
        procs = [{"pid": 1, "comm": "llmster", "cgroup": "/app.slice/lmstudio.service"},
                 {"pid": 2, "comm": "llama-server", "cgroup": "/app.slice/lmstudio.service"}]
        with mock.patch.object(limits, "unit_installed", return_value=True), \
                mock.patch.object(limits, "unit_active", return_value=True), \
                mock.patch.object(limits, "lm_procs", return_value=procs), \
                mock.patch.object(limits, "loaded_models", return_value=None), \
                mock.patch.object(limits, "daemon_ready", return_value=True), \
                mock.patch.object(limits, "_proc_net", return_value=[]), \
                mock.patch.object(limits, "_systemctl") as ctl:
            self.assertIn("in use", limits.reap(now=1000.0))
            ctl.assert_not_called()


class MemoryEmbeddings(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(dir=helpers.SCRATCH)
        self.addCleanup(shutil.rmtree, self.dir, True)
        for name, value in (("DB", os.path.join(self.dir, "m.sqlite3")), ("THUMBS", os.path.join(self.dir, "t")),
                            ("CAPTIONS", os.path.join(self.dir, "c.jsonl")),
                            ("ACTIVITY", os.path.join(self.dir, "a.jsonl"))):
            p = mock.patch.object(dm, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.conf = dict(dm.privacy_settings.DEFAULTS)
        p = mock.patch.object(dm.privacy_settings, "load", side_effect=lambda *a: dict(self.conf))
        p.start()
        self.addCleanup(p.stop)
        self.di = dm.index()
        con = dm.connect()
        dm.add(con, "notifications", time.time() - 60, "something to remember", app="x", title="y", key="k1")
        con.commit()
        con.close()
        if not dm.sources_on(self.conf):
            self.skipTest("the memory is off in privacy_settings.DEFAULTS")

    def test_collect_never_asks_lm_studio(self):
        with mock.patch.object(self.di, "embedding_model") as model, \
                mock.patch.object(self.di, "server_models") as models, \
                mock.patch.object(dm, "snap", return_value=None):
            dm.collect(log=lambda t: None)
        model.assert_not_called()
        models.assert_not_called()

    def test_hourly_with_lm_studio_down_and_a_recent_pass_waits(self):
        con = dm.connect()
        dm.meta(con, "embedded_at", time.time() - 3600)
        con.commit()
        con.close()
        with mock.patch.object(self.di, "server_models", return_value=None), \
                mock.patch.object(self.di, "embedding_model") as model:
            self.assertEqual(dm.embed_hourly(), 0)
        model.assert_not_called()

    def test_hourly_starts_lm_studio_when_long_overdue(self):
        with mock.patch.object(self.di, "server_models", return_value=None), \
                mock.patch.object(self.di, "embedding_model", return_value=None) as model:
            self.assertEqual(dm.embed_hourly(), 0)          # never embedded: overdue
        model.assert_called_once()
        self.assertTrue(model.call_args.kwargs.get("start"))

    def test_hourly_with_lm_studio_up_embeds(self):
        def fake_embed(model, texts, timeout=0):
            import array
            return [array.array("f", [1.0] + [0.0] * 255) for _ in texts]
        with mock.patch.object(self.di, "server_models", return_value=[]), \
                mock.patch.object(self.di, "embedding_model", return_value="fake"), \
                mock.patch.object(self.di, "embed", side_effect=fake_embed):
            self.assertEqual(dm.embed_hourly(), 1)


class BriefTimer(unittest.TestCase):
    def test_unlock_mode_has_no_calendar(self):
        text = brief.timer_dropin({"morning": "unlock", "at": "08:30"})
        self.assertIn("[Timer]", text)
        self.assertNotIn("OnCalendar", text)       # an empty OnCalendar= would clear the login ticks too

    def test_time_mode_rings_at_the_time(self):
        text = brief.timer_dropin({"morning": "time", "at": "07:45"})
        self.assertIn("OnCalendar=*-*-* 07:45:00", text)
        self.assertNotIn("OnCalendar=\n", text)

    def test_schedule_writes_only_on_change(self):
        path = os.path.join(helpers.SCRATCH, "brief.timer.d", "schedule.conf")
        with mock.patch.object(brief.subprocess, "run") as run:
            self.assertTrue(brief.schedule_timer({"morning": "time", "at": "07:45"}, path))
            self.assertFalse(brief.schedule_timer({"morning": "time", "at": "07:45"}, path))
            self.assertTrue(brief.schedule_timer({"morning": "unlock", "at": "07:45"}, path))
        self.assertEqual(run.call_count, 2)                 # daemon-reload per change


class TimersLoop(unittest.TestCase):
    def test_sound_path_is_an_argument_not_shell_text(self):
        nasty = '/tmp/a "b" $(touch x).wav'
        with mock.patch.object(timers, "setting", return_value=100):
            argv = timers.loop_argv(nasty)
        self.assertEqual(argv[:2], ["sh", "-c"])
        self.assertNotIn(nasty, argv[2])
        self.assertEqual(argv[3:], ["sh", "pw-play", nasty])
        self.assertIn('"$@" || sleep 2', argv[2])

    def test_chime_pauses(self):
        with mock.patch.object(timers, "setting", return_value=50):
            argv = timers.loop_argv(timers.CHIME)
        self.assertIn('"$@"; sleep 2', argv[2])
        self.assertIn("--volume=0.50", argv)


class VoiceBar(unittest.TestCase):
    def test_idle_sleeps_long(self):
        self.assertEqual(voice.bar_wait({}, 100.0, True), voice.BAR_IDLE_WATCHED_S)
        self.assertEqual(voice.bar_wait({}, 100.0, False), voice.BAR_IDLE_POLL_S)
        self.assertEqual(voice.bar_wait({"pid": 1, "state": "idle"}, 100.0, True),
                         voice.BAR_IDLE_WATCHED_S)

    def test_captions_look_more_often(self):
        # A daemon that crashes with captions on writes no state: the CC
        # icon goes within BAR_CAPTIONS_S, not a minute later.
        self.assertEqual(voice.bar_wait({"pid": 1, "state": "idle", "captions": True}, 100.0, True),
                         voice.BAR_CAPTIONS_S)

    def test_recording_wakes_on_the_second(self):
        wait = voice.bar_wait({"pid": 1, "state": "recording", "since": 100.0}, 103.25, True)
        self.assertAlmostEqual(wait, 0.77, places=2)

    def test_busy_each_second(self):
        self.assertEqual(voice.bar_wait({"pid": 1, "state": "transcribing"}, 0, True), 1.0)

    def test_watch_names(self):
        def event(name):
            raw = name.encode() + b"\0" * (16 - len(name))
            return struct.pack("=iIII", 1, 0x80, 0, len(raw)) + raw
        self.assertEqual(voice.watch_names(event("voice.state") + event("x.json")), ["voice.state", "x.json"])
        self.assertEqual(voice.watch_names(b""), [])


if __name__ == "__main__":
    unittest.main()
