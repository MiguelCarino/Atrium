"""tts.py (spoken replies) and its hooks: the settings, the language guess,
the text tidied for the ear, when it must stay silent, the queue, the drain
loop (with a fake speaker), the media ducking plan and its undo; brief.py's
spoken brief, voice-command.py's spoken outcome, Settings > Speech's pure
helpers.

Hermetic: tts.conf and the queue live in helpers.py's scratch state and
runtime dirs, every outside command (makoctl, hyprctl, pactl, playerctl,
systemd-run, notify-send) is stubbed, and NOTHING is ever played. The one
real synthesis (skipped without the venv) writes a WAV file into the
scratch dir with `tts.py speak --to`, which never opens an audio device."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
import wave
from unittest import mock

import helpers

tts = helpers.import_script("tts.py", "tts")


def reset():
    for path in (tts.CONF, tts.DUCKED, tts.PIDFILE, tts.LAST):
        if os.path.exists(path):
            os.remove(path)
    shutil.rmtree(tts.QUEUE, ignore_errors=True)


class Settings(unittest.TestCase):
    def setUp(self):
        reset()
        self.voices = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.voices, True)
        for name in ("es_MX-ald-medium", "es_ES-davefx-medium", "en_US-lessac-medium"):
            for ext in (".onnx", ".onnx.json"):
                open(os.path.join(self.voices, name + ext), "w").close()
        open(os.path.join(self.voices, "en_US-broken-medium.onnx"), "w").close()     # no .json: not a voice
        patch = mock.patch.object(tts, "VOICES", self.voices)
        patch.start()
        self.addCleanup(patch.stop)

    tearDown = staticmethod(reset)

    def test_defaults_ship_quiet_features(self):
        conf = tts.settings()
        self.assertEqual((conf["enabled"], conf["speak_brief"], conf["speak_commands"]), ("on", "off", "off"))
        self.assertEqual((conf["rate"], conf["volume"], conf["duck"]), ("100", "80", "lower"))

    def test_set_validates_and_reads_back(self):
        self.assertEqual(tts.set_setting("rate", "130%"), "130")
        self.assertEqual(tts.set_setting("voice_es", "es_ES-davefx-medium"), "es_ES-davefx-medium")
        self.assertEqual(tts.settings()["rate"], "130")
        for key, value in (("rate", "20"), ("rate", "fast"), ("duck", "loud"), ("voice_es", "en_US-lessac-medium"),
                           ("voice_en", "en_US-ryan-medium"), ("nope", "1"), ("speak_brief", "yes")):
            with self.assertRaises(ValueError, msg=(key, value)):
                tts.set_setting(key, value)

    def test_a_bad_line_in_the_file_is_its_default(self):
        os.makedirs(os.path.dirname(tts.CONF), exist_ok=True)
        with open(tts.CONF, "w") as h:
            h.write("rate=999\nvolume=50\njunk\n")
        conf = tts.settings()
        self.assertEqual((conf["rate"], conf["volume"]), ("100", "50"))

    def test_installed_voices_and_choice(self):
        self.assertEqual(tts.installed_voices(), {"es": ["es_ES-davefx-medium", "es_MX-ald-medium"],
                                                 "en": ["en_US-lessac-medium"]})
        self.assertEqual(tts.voice_for("es"), "es_MX-ald-medium")
        self.assertEqual(tts.voice_for("es", {"voice_es": "es_AR-daniela-high"}), "es_ES-davefx-medium")


class Words(unittest.TestCase):
    def test_language_guess(self):
        for text, lang in (("¿Qué hora es?", "es"), ("Hoy hay una reunión con el equipo", "es"),
                           ("The build passed and the tests are green", "en"), ("Mañana", "es"),
                           ("Atlas", "en"), ("Está listo", "es")):
            self.assertEqual(tts.guess_lang(text), lang, text)

    def test_pick_lang_order(self):
        self.assertEqual(tts.pick_lang("hello there", "es", {"language": "en"}), "es")
        self.assertEqual(tts.pick_lang("hello there", "auto", {"language": "es"}), "es")
        self.assertEqual(tts.pick_lang("hola, ¿cómo estás?", None, {"language": "auto"}), "es")

    def test_clean_for_the_ear(self):
        text = "# Done\n- moved **Firefox** to `3`\nsee [the docs](https://x.org/a) or https://y.org/b\n" \
               "```\nrm -rf /\n```\nok"
        self.assertEqual(tts.clean(text, "en"), "Done. moved Firefox to 3. see the docs or a link. ok.")
        self.assertIn("un enlace", tts.clean("mira https://x.org", "es"))
        self.assertEqual(tts.clean("<b>Hi</b> &amp; bye"), "Hi & bye.")

    def test_long_text_is_cut_at_a_sentence(self):
        text = "First sentence here. " * 60
        out = tts.clean(text, "en", 200)
        self.assertLessEqual(len(out), 200)
        self.assertTrue(out.endswith("."))
        self.assertTrue(tts.clean("word " * 100, "en", 120).endswith("…"))


class Silence(unittest.TestCase):
    def setUp(self):
        reset()
        self.probes = []
        for name, value in (("gamemode_on", False), ("dnd_on", False), ("quiet_hours", False),
                            ("engine_ready", True)):
            patch = mock.patch.object(tts, name, self.probe(name, value))
            patch.start()
            self.addCleanup(patch.stop)

    tearDown = staticmethod(reset)

    def probe(self, name, value):
        def fn(*_a, **_k):
            self.probes.append(name)
            return getattr(self, name, value)
        return fn

    def test_switched_off_asks_nothing_else(self):
        self.assertIn("speech is off", tts.blocked(None, dict(tts.DEFAULTS, enabled="off")))
        self.assertIn("brief", tts.blocked("brief", tts.settings()))           # off as shipped
        self.assertEqual(self.probes, [])

    def test_gamemode_dnd_quiet_hours(self):
        conf = dict(tts.DEFAULTS, speak_commands="on")
        self.assertEqual(tts.blocked("commands", conf), "")
        self.gamemode_on = True
        self.assertEqual(tts.blocked("commands", conf), "gamemode is on")
        self.gamemode_on, self.dnd_on = False, True
        self.assertEqual(tts.blocked("commands", conf), "Do Not Disturb is on")
        self.assertEqual(tts.blocked("commands", dict(conf, quiet="off")), "")    # quiet off: DND does not count
        self.dnd_on, self.quiet_hours = False, True
        self.assertEqual(tts.blocked(None, conf), "quiet hours")

    def test_a_click_on_test_speaks_whatever_the_switches(self):
        self.gamemode_on = self.dnd_on = True
        self.assertEqual(tts.blocked("test", dict(tts.DEFAULTS, enabled="off")), "")
        self.engine_ready = False
        self.assertIn("not installed", tts.blocked("test"))

    def test_speak_queues_and_starts_one_drain(self):
        with mock.patch.object(tts, "start_drain", return_value=True) as start:
            self.assertTrue(tts.speak("Hola, ¿qué tal?"))
            self.assertFalse(tts.speak("brief words", feature="brief"))
            self.assertIn("brief", tts.last_reason)
            self.assertFalse(tts.speak("```code only```"))
        self.assertEqual(start.call_count, 1)
        item = tts.take()
        self.assertEqual((item["text"], item["lang"]), ("Hola, ¿qué tal?", "es"))
        self.assertIsNone(tts.take())


class Queue(unittest.TestCase):
    setUp = tearDown = staticmethod(reset)

    def test_order_limit_and_modes(self):
        for i in range(tts.MAX_QUEUE + 3):
            tts.enqueue({"text": str(i)})
        files = tts.queued()
        self.assertEqual(len(files), tts.MAX_QUEUE)
        self.assertEqual(os.stat(tts.QUEUE).st_mode & 0o777, 0o700)
        self.assertEqual(os.stat(files[0]).st_mode & 0o777, 0o600)
        self.assertEqual(tts.take()["text"], "3")             # the oldest went first

    def test_drain_argv_is_a_transient_unit_under_the_venv(self):
        with mock.patch.object(tts.shutil, "which", return_value="/usr/bin/systemd-run"):
            argv = tts.drain_argv()
        self.assertEqual(argv[:2], ["systemd-run", "--user"])
        self.assertEqual(argv[-3:], [tts.VENV_PY, tts.THIS, "_drain"])
        self.assertIn(f"--setenv=XDG_RUNTIME_DIR={os.environ['XDG_RUNTIME_DIR']}", argv)

    def test_drain_says_everything_in_order_then_cleans_up(self):
        said = []

        class FakeSpeaker:
            def __init__(self, conf):
                self.stopped, self.player = False, None

            def stop(self, *_):
                self.stopped = True

            def say(self, item):
                said.append(item["text"])
                if item["text"] == "a":
                    tts.enqueue({"text": "late"})          # queued while it talks: still said

            def finish(self):
                said.append("finish")
        for t in ("a", "b"):
            tts.enqueue({"text": t})
        with mock.patch.object(tts, "Speaker", FakeSpeaker), mock.patch.object(tts.signal, "signal"), \
                mock.patch.object(tts, "restore_duck") as undo, mock.patch.object(tts, "blocked", return_value=""):
            self.assertEqual(tts.drain(), "done")
        self.assertEqual(said, ["a", "b", "late", "finish"])
        self.assertTrue(undo.called)
        self.assertFalse(os.path.exists(tts.PIDFILE) and tts.speaking_pid())
        self.assertEqual(tts.queued(), [])

    def test_stop_without_a_drain_empties_and_undoes(self):
        tts.enqueue({"text": "x"})
        with mock.patch.object(tts, "restore_duck") as undo:
            self.assertFalse(tts.stop())
        self.assertEqual(tts.queued(), [])
        self.assertTrue(undo.called)


class Robustness(unittest.TestCase):
    """The review's breakages: each one used to crash, leak or unduck."""
    setUp = tearDown = staticmethod(reset)

    def fake_speaker(self, said):
        class FakeSpeaker:
            def __init__(self, conf):
                self.stopped, self.player = False, None

            def stop(self, *_):
                self.stopped = True

            def say(self, item):
                said.append(item.get("text") or item.get("wav"))

            def finish(self):
                said.append("finish")
        return FakeSpeaker

    def test_nothing_sayable_is_not_queued(self):
        for text in ("…", "?", "---", "* * *", "¿?"):
            self.assertEqual(tts.clean(text), "", text)
        self.assertEqual(tts.clean("Sí."), "Sí.")

    def test_a_line_piper_makes_no_sound_of_does_not_kill_the_drain(self):
        speaker = tts.Speaker(dict(tts.DEFAULTS))
        speaker.voices["en_US-lessac-medium"] = types.SimpleNamespace(synthesize=lambda *a: iter(()))
        with mock.patch.object(tts, "duck"), mock.patch.object(tts, "voice_for", return_value="en_US-lessac-medium"), \
                mock.patch.object(tts, "syn_config", return_value=None), mock.patch.object(tts, "LAST", os.devnull):
            speaker.say({"text": "…", "lang": "en"})                 # used to be None * float: TypeError
        broken = tts.Speaker(dict(tts.DEFAULTS))
        with mock.patch.object(tts, "duck"), mock.patch.object(tts, "voice_for", return_value="x"), \
                mock.patch.object(tts, "load_voice", side_effect=RuntimeError("bad onnx")):
            self.assertIsNone(broken.say({"text": "hello", "lang": "en"}))     # logged, not raised

    def test_drain_rechecks_before_each_line(self):
        said = []
        wav = tts.tmp_wav("test")
        open(wav, "wb").close()
        tts.enqueue({"text": "brief line", "feature": "brief"})
        tts.enqueue({"wav": wav, "feature": "test"})
        with mock.patch.object(tts, "Speaker", self.fake_speaker(said)), mock.patch.object(tts.signal, "signal"), \
                mock.patch.object(tts, "restore_duck"), \
                mock.patch.object(tts, "blocked", side_effect=lambda f=None, *a: "gamemode is on" if f != "test" else ""):
            tts.drain()
        self.assertEqual(said, [wav, "finish"])                     # the click still plays
        tts._unlink(wav)

    def test_a_drain_that_loses_the_lock_leaves_the_new_ones_ducking_alone(self):
        said = []
        Fake = self.fake_speaker(said)

        def finish(_self):
            said.append("finish")
            tts.enqueue({"text": "late"})                   # queued as it lets go: a new drain takes it
        Fake.finish = finish
        tts.enqueue({"text": "a"})
        locks = iter([True, False])
        with mock.patch.object(tts, "Speaker", Fake), mock.patch.object(tts.signal, "signal"), \
                mock.patch.object(tts, "_try_lock", side_effect=lambda h: next(locks)), \
                mock.patch.object(tts, "blocked", return_value=""), mock.patch.object(tts, "restore_duck") as undo:
            tts.drain()
        self.assertEqual(said, ["a", "finish"])
        self.assertEqual(undo.call_count, 1)                # the start-up one only, not the finally's
        self.assertEqual(len(tts.queued()), 1)              # left for the drain that holds the lock

    def test_stop_and_trim_remove_the_test_wav_too(self):
        wav = tts.tmp_wav("test")
        open(wav, "wb").close()
        tts.enqueue({"wav": wav, "feature": "test"})
        with mock.patch.object(tts, "restore_duck"):
            tts.stop()
        self.assertFalse(os.path.exists(wav))
        outside = os.path.join(helpers.SCRATCH, "keep.wav")
        open(outside, "wb").close()
        tts.enqueue({"wav": outside})
        for i in range(tts.MAX_QUEUE):
            tts.enqueue({"text": str(i)})
        self.assertTrue(os.path.exists(outside))            # only our own tmpfs files are deleted

    def test_speaking_pid_is_only_a_drain(self):
        os.makedirs(tts.RUN_DIR, exist_ok=True)
        with open(tts.PIDFILE, "w") as handle:
            handle.write(str(os.getpid()))                  # this test process: not a drain
        self.assertIsNone(tts.speaking_pid())


class Ducking(unittest.TestCase):
    setUp = tearDown = staticmethod(reset)

    INPUTS = [{"index": 7, "properties": {"application.name": "Firefox"},
               "volume": {"front-left": {"value": 65536}, "front-right": {"value": 32768}}},
              {"index": 8, "properties": {"application.name": tts.APP_NAME}, "volume": {"mono": {"value": 65536}}},
              {"index": 9, "corked": True, "properties": {}, "volume": {"mono": {"value": 65536}}}]

    def test_plan_lower_skips_ours_and_paused(self):
        plan = tts.duck_plan(dict(tts.DEFAULTS, duck_level="25"), self.INPUTS, [])
        self.assertEqual(plan, {"how": "lower", "inputs": {"7": {"was": [65536, 32768], "now": [16384, 8192]}}})
        self.assertEqual(tts.duck_plan(dict(tts.DEFAULTS, duck="pause"), [], ["mpv"]),
                         {"how": "pause", "players": ["mpv"]})
        self.assertEqual(tts.duck_plan(dict(tts.DEFAULTS, duck="off"), self.INPUTS, ["mpv"]), {"how": "off"})

    def test_duck_then_restore_exactly(self):
        calls = []
        with mock.patch.object(tts, "run", lambda *c, **k: calls.append(list(c)) or ""), \
                mock.patch.object(tts, "sink_inputs", return_value=self.INPUTS):
            tts.duck(tts.settings())
            self.assertTrue(os.path.exists(tts.DUCKED))            # written before anything changed
            self.assertTrue(tts.restore_duck())
            self.assertFalse(tts.restore_duck())                   # once
        self.assertEqual(calls, [["pactl", "set-sink-input-volume", "7", "16384", "8192"],
                                 ["pactl", "set-sink-input-volume", "7", "65536", "32768"]])

    def test_pause_resumes_only_what_was_playing(self):
        calls = []
        with mock.patch.object(tts, "run", lambda *c, **k: calls.append(list(c)) or ""), \
                mock.patch.object(tts, "playing_players", return_value=["spotify"]):
            tts.duck(dict(tts.DEFAULTS, duck="pause"))
            tts.restore_duck()
        self.assertEqual(calls, [["playerctl", "-p", "spotify", "pause"], ["playerctl", "-p", "spotify", "play"]])

    def test_player_argv(self):
        argv = tts.player_argv(22050, dict(tts.DEFAULTS, volume="60"))
        self.assertEqual(argv[:4], ["pw-play", "--raw", "--rate", "22050"])
        self.assertIn("0.60", argv)
        self.assertEqual(argv[-1], "-")


class Selection(unittest.TestCase):
    setUp = tearDown = staticmethod(reset)

    def test_private_window_is_never_read(self):
        fake = types.SimpleNamespace(hypr_json=lambda *a: {"class": "org.keepassxc.KeePassXC"},
                                     is_private=lambda c, p=(): "keepass" in c["class"].lower(),
                                     private_classes=lambda: set())
        with mock.patch.dict(sys.modules, {"voice_command": fake}), \
                mock.patch.object(tts, "run", side_effect=AssertionError("wl-paste must not run")):
            self.assertEqual(tts.read_selection(), ("", "a private window"))

    def test_key_again_stops(self):
        with mock.patch.object(tts, "speaking_pid", return_value=123), mock.patch.object(tts, "stop") as stop:
            self.assertEqual(tts.speak_selection(), "stopped")
        self.assertTrue(stop.called)


@unittest.skipUnless(os.access(tts.VENV_PY, os.X_OK) and tts.voice_for("es", dict(tts.DEFAULTS)),
                     "Piper venv or voices not installed")
class RealSynthesis(unittest.TestCase):
    def test_render_to_file_only(self):
        out = os.path.join(helpers.SCRATCH, "hola.wav")
        done = subprocess.run([sys.executable, os.path.join(helpers.SCRIPTS, "tts.py"), "speak",
                               "Hola, esto es una prueba.", "--lang", "es", "--to", out, "--json"],
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        result = json.loads(done.stdout)
        self.assertEqual(result["lang"], "es")
        with wave.open(out) as w:
            self.assertGreater(w.getnframes() / w.getframerate(), 0.8)
        self.assertLess(result["rtf"], 1.0)
        self.assertEqual(tts.queued(), [])                       # nothing went to the speaker


class Hooks(unittest.TestCase):
    def test_brief_spoken_for_the_ear(self):
        brief_mod = helpers.import_script("brief.py")
        import datetime as dt
        text = brief_mod.spoken([
            {"id": "yesterday", "title": "Where you left off",
             "lines": ["Yesterday: 2 h 05 min at the computer, 09:00-17:30 -- kitty 45 min", "more"]},
            {"id": "units", "title": "Failed services",
             "lines": ["Yours: run-p1.service, a-b@c.timer  (journalctl --user -u NAME)"]},
            {"id": "weather", "title": "Weather", "lines": ["today 12..18°C"]},
            {"id": "repos", "title": "Repos", "lines": ["dotfiles: 3 to sync from ~."]}],
            now=dt.datetime(2026, 10, 21, 8, 0))
        self.assertEqual(text.splitlines(), [
            "Good morning. Wednesday 21 October.",
            "Where you left off: Yesterday: 2 hours 05 minutes at the computer, 09:00 to 17:30. kitty 45 minutes.",
            "Failed services: Yours: several services.",
            "Weather: today 12 to 18°C.",
            "Repos: dotfiles: 3 to sync from home."])

    def test_brief_reads_aloud_through_tts(self):
        brief_mod = helpers.import_script("brief.py")
        fake = types.SimpleNamespace(speak=mock.Mock(return_value=True))
        with mock.patch.dict(sys.modules, {"tts": fake}):
            self.assertTrue(brief_mod.say_aloud([]))
        self.assertEqual(fake.speak.call_args.kwargs, {"lang": "en", "feature": "brief"})

    def test_voice_command_says_the_outcome(self):
        vc = helpers.import_script("voice-command.py")
        fake = types.SimpleNamespace(speak=mock.Mock(return_value=True))
        notes = types.SimpleNamespace(tell=lambda *a, **k: None, buttons=lambda *a, **k: None)
        refused = {"actions": [], "sure": True, "error": "not something I can do", "how": "fast"}
        with mock.patch.dict(sys.modules, {"tts": fake}), mock.patch.object(vc, "understand", return_value=refused), \
                mock.patch.object(vc, "log", lambda t: None):
            result = vc.handle("haz magia", "es", world=object(), notifier=notes,
                               conf={"commands": "on", "confirm": False, "language": "auto"})
        self.assertEqual(result["result"], "refused")
        args, kwargs = fake.speak.call_args
        self.assertEqual(args, ("No se hizo: not something I can do",))
        self.assertEqual(kwargs, {"lang": "es", "feature": "commands"})

    def test_assistant_finds_the_hook(self):
        assistant = helpers.import_script("assistant.py")
        self.assertTrue(callable(assistant.tts_function()))


class PageHelpers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import gi
            gi.require_version("Gtk", "3.0")
            gi.require_version("Gdk", "3.0")
            from settings_pages import speech as page
        except Exception as exc:                                    # noqa: BLE001
            raise unittest.SkipTest(f"settings_pages.speech not importable: {exc}")
        cls.page = page

    def test_voice_caption(self):
        self.assertEqual(self.page.voice_caption("es_MX-ald-medium"), "ald · Mexico · medium")
        self.assertEqual(self.page.voice_caption("en_GB-northern_english_male-medium"),
                         "northern english male · UK · medium")
        self.assertEqual(self.page.voice_caption("odd"), "odd")

    def test_engine_line(self):
        base = {"settings": {"x": 1}, "installed": True, "voices": {"es": ["a"], "en": ["b"]}}
        self.assertTrue(self.page.engine_line(base).startswith("Ready"))
        self.assertTrue(self.page.engine_line(dict(base, blocked="gamemode is on")).startswith("Silent now: gamemode"))
        self.assertTrue(self.page.engine_line(dict(base, speaking=True, queued=2)).startswith("Speaking now, 2 more"))
        self.assertIn("Not installed", self.page.engine_line(dict(base, installed=False)))
        self.assertEqual(self.page.engine_line(None), "tts.py did not answer")

    def test_test_line(self):
        line = self.page.test_line({"voice": "es_MX-ald-medium", "audio_s": 5.0, "synth_s": 0.1, "rtf": 0.02,
                                    "load_s": 1.0, "played": True})
        self.assertEqual(line, "Playing: ald · Mexico · medium  ·  50× faster than real time")
        self.assertEqual(self.page.test_line({"error": "x"}), "Not played: x")


if __name__ == "__main__":
    unittest.main()
