"""scripts/voice.py (voice typing and live captions): the settings file, the
engine choice, the text-out commands, the captions chunking, the silence
phrases, the bar pill -- and settings_pages/voice.py's engine line.

Hermetic: voice.conf is helpers.py's scratch XDG_STATE_HOME, no daemon is
started, no model loaded, nothing recorded and nothing typed (deliver()'s
subprocess.run is stubbed)."""
import math
import os
import struct
import unittest
from unittest import mock

import helpers

voice = helpers.import_script("voice.py")


def tone(seconds, amplitude=8000, rate=16000):
    """s16 mono: a 440 Hz tone (loud) or, with amplitude 0, silence."""
    n = int(seconds * rate)
    return struct.pack(f"<{n}h", *(int(amplitude * math.sin(2 * math.pi * 440 * i / rate)) for i in range(n)))


class Settings(unittest.TestCase):
    def setUp(self):
        if os.path.exists(voice.CONF):
            os.remove(voice.CONF)

    tearDown = setUp

    def test_defaults(self):
        s = voice.read_settings()
        self.assertEqual((s["model"], s["device"], s["language"], s["output"]), ("large-v3-turbo", "auto", "auto", "type"))
        self.assertEqual((s["idle_min"], s["in_games"], s["translate"]), ("5", "off", "off"))

    def test_set_keeps_only_changes(self):
        voice.write_setting("language", "ES")
        voice.write_setting("idle_min", "12")
        self.assertEqual(voice.read_settings()["language"], "es")
        voice.write_setting("idle_min", "5")                      # back to the default: dropped
        with open(voice.CONF) as handle:
            self.assertEqual(handle.read(), "language=es\n")

    def test_refuses_bad_values(self):
        for key, value in (("model", "huge"), ("idle_min", "0"), ("idle_min", "x"), ("caption_size", "99"),
                           ("nope", "1"), ("output", "")):
            with self.assertRaises(ValueError, msg=(key, value)):
                voice.write_setting(key, value)

    def test_hand_edited_garbage_reads_as_default(self):
        os.makedirs(os.path.dirname(voice.CONF), exist_ok=True)
        with open(voice.CONF, "w") as handle:
            handle.write("model=enormous\noutput=paste\nnot a line\n")
        s = voice.read_settings()
        self.assertEqual((s["model"], s["output"]), ("large-v3-turbo", "paste"))


class Engine(unittest.TestCase):
    S = dict(voice.DEFAULTS)

    def plan(self, free, gaming=False, **over):
        return voice.plan_engine({**self.S, **over}, free, gaming)

    def test_card_when_it_fits(self):
        self.assertEqual(self.plan(8000)[:3], ("cuda", "large-v3-turbo", "int8_float16"))

    def test_cpu_when_the_card_is_full(self):
        device, model, compute, why = self.plan(1500)          # an LLM holds the rest
        self.assertEqual((device, model, compute), ("cpu", "small", "int8"))
        self.assertIn("GB free", why)
        self.assertIsNone(self.plan(1500, device="cuda")[0])   # card only: refused instead

    def test_gamemode_refuses_unless_cpu_is_fine(self):
        device, _m, _c, why = self.plan(20000, gaming=True)
        self.assertIsNone(device)
        self.assertIn("gamemode", why)
        self.assertEqual(self.plan(20000, gaming=True, in_games="cpu")[0], "cpu")
        self.assertEqual(self.plan(20000, gaming=True, device="cpu")[0], "cpu")

    def test_no_card(self):
        self.assertEqual(self.plan(None)[0], "cpu")
        self.assertIsNone(self.plan(None, device="cuda")[0])

    def test_bigger_model_needs_more_room(self):
        self.assertEqual(self.plan(2500, model="small")[0], "cuda")
        self.assertEqual(self.plan(2500, model="large-v3")[0], "cpu")

    def test_cuda_lib_dirs_and_cached_models(self):
        root = os.path.join(helpers.SCRATCH, "venv")
        for pkg in ("cublas", "cudnn"):
            os.makedirs(os.path.join(root, "lib", "python3.14", "site-packages", "nvidia", pkg, "lib"), exist_ok=True)
        self.assertEqual([os.path.basename(os.path.dirname(d)) for d in voice.cuda_lib_dirs(root)], ["cublas", "cudnn"])
        models = os.path.join(helpers.SCRATCH, "models")
        os.makedirs(os.path.join(models, "models--mobiuslabsgmbh--faster-whisper-large-v3-turbo"), exist_ok=True)
        os.makedirs(os.path.join(models, "models--Systran--faster-whisper-small"), exist_ok=True)
        self.assertEqual(voice.cached_models(models), ["large-v3-turbo", "small"])


class TextOut(unittest.TestCase):
    def test_argvs(self):
        self.assertEqual(voice.output_argvs("hola", "type"), [["wtype", "--", "hola"]])
        self.assertEqual(voice.output_argvs("-x", "copy"), [["wl-copy", "--", "-x"]])
        paste = voice.output_argvs("hi", "paste")
        self.assertEqual(paste[0], ["wl-copy", "--", "hi"])
        self.assertEqual(paste[1], ["wtype", "-M", "ctrl", "-k", "v", "-m", "ctrl"])

    def test_deliver_runs_them_in_order_and_types_nothing_here(self):
        with mock.patch.object(voice.subprocess, "run") as run, mock.patch.object(voice.time, "sleep"):
            self.assertTrue(voice.deliver("Mañana", "paste"))
        self.assertEqual([c.args[0][0] for c in run.call_args_list], ["wl-copy", "wtype"])

    def test_clean_text_drops_silence_phrases(self):
        self.assertEqual(voice.clean_text([{"text": " Hola", "no_speech": 0.1}, {"text": " mundo.", "no_speech": 0.2}]),
                         "Hola mundo.")
        self.assertEqual(voice.clean_text([{"text": " Thank you.", "no_speech": 0.3}]), "")
        self.assertEqual(voice.clean_text([{"text": " Gracias.", "no_speech": 0.1}]), "")
        self.assertEqual(voice.clean_text([{"text": " real words", "no_speech": 0.9}]), "")
        self.assertEqual(voice.clean_text([{"text": "Thank you for coming.", "no_speech": 0.1}]), "Thank you for coming.")


class CaptionChunks(unittest.TestCase):
    def kinds(self, cut, pcm, piece=1234):
        out = []
        for i in range(0, len(pcm), piece):                     # odd-sized reads, like a pipe gives
            out += [(kind, len(data) / voice.BYTES_PER_S) for kind, data in cut.feed(pcm[i:i + piece])]
        return out

    def test_silence_is_never_sent_and_does_not_pile_up(self):
        cut = voice.Captions()
        self.assertEqual(self.kinds(cut, tone(10, 0)), [])
        self.assertLessEqual(len(cut.buf), 11 * voice.BLOCK)     # at most ~1 s of quiet is held

    def test_a_phrase_then_a_pause_is_drafted_then_final(self):
        cut = voice.Captions()
        work = self.kinds(cut, tone(3) + tone(1, 0))
        kinds = [k for k, _ in work]
        self.assertIn("draft", kinds)
        self.assertEqual(kinds[-1], "final")
        self.assertEqual(kinds.count("final"), 1)
        self.assertAlmostEqual(work[-1][1], 3 + voice.PAUSE_S, delta=0.15)
        self.assertFalse(any(cut.loud))                          # only the quiet after it is left

    def test_long_talk_is_cut_at_max(self):
        cut = voice.Captions()
        finals = [s for k, s in self.kinds(cut, tone(20)) if k == "final"]
        self.assertEqual(len(finals), 2)
        self.assertTrue(all(abs(s - voice.MAX_S) < 0.15 for s in finals))


class Bar(unittest.TestCase):
    def test_states(self):
        self.assertEqual(voice.bar_status({})["class"], "idle")
        self.assertEqual(voice.bar_status({})["text"], "")
        rec = voice.bar_status({"state": "recording", "since": 100, "engine": "x"}, now=165)
        self.assertEqual(rec["class"], "recording")
        self.assertIn("1:05", rec["text"])
        self.assertEqual(voice.bar_status({"state": "transcribing"})["class"], "busy")
        self.assertEqual(voice.bar_status({"state": "idle", "captions": True})["class"], "captions")

    def test_dead_daemon_reads_as_nothing(self):
        path = os.path.join(helpers.SCRATCH, "voice.state")
        with open(path, "w") as handle:
            handle.write('{"pid": 999999999, "state": "recording"}')
        self.assertEqual(voice.read_state(path), {})
        with open(path, "w") as handle:
            handle.write('{"pid": %d, "state": "recording"}' % os.getpid())
        self.assertEqual(voice.read_state(path)["state"], "recording")


class Page(unittest.TestCase):
    """settings_pages/voice.py's engine line (GTK imported, nothing shown)."""

    @classmethod
    def setUpClass(cls):
        try:
            import gi
            gi.require_version("Gtk", "3.0")                     # settings.py does this before any page loads
            gi.require_version("Gdk", "3.0")
            from settings_pages import voice as page
        except Exception as exc:                                 # no display / GTK
            raise unittest.SkipTest(f"settings_pages.voice not importable: {exc}")
        cls.page = page

    def test_engine_line(self):
        base = {"installed": True, "gpu_free_mb": 8192, "models": ["large-v3-turbo"]}
        line = self.page.engine_line({**base, "worker": {"device": "cuda", "model": "large-v3-turbo", "idle_s": 130}})
        self.assertIn("large-v3-turbo loaded on the graphics card, unused for 2 min", line)
        self.assertIn("8.0 GB free", line)
        line = self.page.engine_line({**base, "worker": None, "plan": ["cpu", "small", "int8", "the card is full"]})
        self.assertIn("loads small on the CPU (the card is full)", line)
        line = self.page.engine_line({**base, "worker": None, "plan": [None, None, None, "gamemode is on"]})
        self.assertIn("Paused: gamemode is on", line)
        self.assertIn("Not installed", self.page.engine_line({"installed": False}))

    def test_page_dict_is_literal_and_findable(self):
        self.assertEqual(self.page.PAGE["id"], "voice")
        for word in ("dictation", "captions", "subtitles", "whisper", "speech to text", "voice typing"):
            self.assertIn(word, self.page.PAGE["keywords"])


if __name__ == "__main__":
    unittest.main()
