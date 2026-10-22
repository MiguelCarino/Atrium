"""scripts/gestures.py (gestures and gaze on presence's camera): the poses
read from hand landmarks, the swipe / hold recognizer (deliberate: a held
pose, let go before it fires again, a cooldown, nothing without a face
turned to the screens), head pose -> monitor with per-monitor calibration
and dwell, the fixed action catalog (the Confirm bubble found through
makoctl, nothing when there is none, nothing while locked), the gaze focus
guard, the CPU budget, the settings; presence.py's watcher handing frames
to it and looking faster only while it is on; privacy_settings' two new
switches (off as shipped) and the page's wording.

Hermetic: no camera, no OpenCV, no makoctl / hyprctl (a recording runner).
The landmark sequences in fixtures/ were recorded from the real hand and
face models on sample photos (~/.local/share/presence/samples), never from
the webcam; `gestures.py test-image FILE` tries the models on photos by hand."""
import json
import os
import tempfile
import unittest
from unittest import mock

import helpers

G = helpers.import_script("gestures.py")
G.log = lambda *_a, **_k: None
P = helpers.import_script("presence.py")
P.log = lambda *_a, **_k: None
import privacy_settings  # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
SIZE = (640, 480)


def fixture(name):
    with open(os.path.join(FIX, name)) as handle:
        return [json.loads(line) for line in handle if line.strip() and not line.startswith("#")]


THUMBS = fixture("gestures-thumbs-up.jsonl")[0]
DOWN = fixture("gestures-thumbs-down.jsonl")[0]
PALM = fixture("gestures-swipe.jsonl")[0]
FRONT = THUMBS["face"]


class Runner:
    """Records argv; answers a few read-only queries from canned output."""

    def __init__(self, answers=None):
        self.calls, self.answers = [], answers or {}

    def __call__(self, *argv, **_kw):
        self.calls.append(list(argv))
        for key, out in self.answers.items():
            if tuple(argv[:len(key)]) == key:
                return out
        return ""

    def ran(self, first):
        return [c for c in self.calls if c[0] == first]


def hand(pose, x=0.5, y=0.5, w=0.2):
    return {"pose": pose, "x": x, "y": y, "w": w}


class Poses(unittest.TestCase):
    def test_recorded_hands(self):
        self.assertEqual(G.classify(THUMBS["hands"][0]["world"], THUMBS["hands"][0]["screen"]), "thumbs_up")
        self.assertEqual(G.classify(DOWN["hands"][0]["world"], DOWN["hands"][0]["screen"]), "thumbs_down")
        self.assertEqual(G.classify(PALM["hands"][0]["world"], PALM["hands"][0]["screen"]), "open_palm")

    def test_sideways_thumb_is_nothing(self):
        h = THUMBS["hands"][0]
        turned = [[-p[1], p[0], p[2]] for p in h["screen"]]      # the picture turned 90 degrees
        self.assertIsNone(G.classify(h["world"], turned))

    def test_missing_or_short(self):
        self.assertIsNone(G.classify(None, None))
        self.assertIsNone(G.classify([[0, 0, 0]] * 5, [[0, 0, 0]] * 5))

    def test_summary_drops_small_hands(self):
        h = THUMBS["hands"][0]
        s = G.hand_summary(h, SIZE)
        self.assertEqual(s["pose"], "thumbs_up")
        self.assertTrue(0 < s["x"] < 1 and 0 < s["y"] < 1)
        self.assertIsNone(G.hand_summary(h, (20000, 15000)))          # tiny in a huge picture


class RecognizerTest(unittest.TestCase):
    def setUp(self):
        self.r = G.Recognizer(hold_s=0.8, swipe=0.25)

    def feed(self, poses, start=0.0, step=0.1, **kw):
        out = []
        for i, p in enumerate(poses):
            got = self.r.feed(hand(p, **kw) if p != "-" else None, start + i * step)
            if got:
                out.append((round(start + i * step, 2), got))
        return out

    def test_hold_fires_once_then_needs_letting_go(self):
        self.assertEqual(self.feed(["thumbs_up"] * 30), [(0.8, "thumbs_up")])
        # let go (half a second of another pose), past the cooldown: fires again
        got = self.feed(["fist"] * 5 + ["thumbs_up"] * 10, start=3.1)
        self.assertEqual([g for _t, g in got], ["thumbs_up"])

    def test_flicker_is_not_letting_go(self):
        self.feed(["thumbs_up"] * 9)
        got = self.feed(["thumbs_up", None, "thumbs_up"] * 10, start=0.9)
        self.assertEqual(got, [])

    def test_short_hold_and_moving_hand_do_nothing(self):
        self.assertEqual(self.feed(["open_palm"] * 6), [])
        r = G.Recognizer(hold_s=0.8, swipe=0.9)
        fired = [r.feed(hand("open_palm", x=0.3 + 0.03 * (i % 2) * 4), i / 10) for i in range(20)]
        self.assertEqual([f for f in fired if f], [])

    def test_swipe_direction_and_swap(self):
        xs = [0.8, 0.65, 0.5, 0.35]
        got = [self.r.feed(hand(None, x=x), i / 10) for i, x in enumerate(xs)]
        self.assertIn("swipe_right", got)         # the picture's right to left = the user's right
        r = G.Recognizer(swipe=0.25, swap=True)
        got = [r.feed(hand(None, x=x), i / 10) for i, x in enumerate(xs)]
        self.assertIn("swipe_left", got)
        r = G.Recognizer(swipe=0.25)
        got = [r.feed(hand(None, x=x), i / 10) for i, x in enumerate(reversed(xs))]
        self.assertIn("swipe_left", got)

    def test_vertical_and_slow_moves_are_not_swipes(self):
        got = [self.r.feed(hand(None, x=0.5 + 0.02 * i, y=0.2 + 0.15 * i), i / 10) for i in range(5)]
        self.assertEqual([g for g in got if g], [])
        r = G.Recognizer(swipe=0.25)
        got = [r.feed(hand(None, x=0.8 - 0.02 * i), i / 10) for i in range(30)]   # 0.6 in 3 s
        self.assertEqual([g for g in got if g], [])

    def test_cooldown_after_a_swipe(self):
        for i, x in enumerate([0.8, 0.6, 0.4, 0.2]):
            self.r.feed(hand(None, x=x), i / 10)
        got = [self.r.feed(hand(None, x=x), 0.4 + i / 10) for i, x in enumerate([0.8, 0.6, 0.4])]
        self.assertEqual([g for g in got if g], [])

    def test_return_stroke_after_a_swipe_is_not_a_swipe_back(self):
        # the hand swipes, then goes back the other way during the cooldown and rests
        moves = [(i / 10, 0.3 + i / 10) for i in range(5)] + [(0.5 + i / 10, 0.7 - i / 10) for i in range(5)]
        moves += [(1.0 + i / 10, 0.3) for i in range(10)]
        got = [g for g in (self.r.feed(hand(None, x=x), t) for t, x in moves) if g]
        self.assertEqual(got, ["swipe_left"])

    def test_gone_hand_resets(self):
        self.feed(["victory"] * 6)
        self.feed(["-"] * 5, start=0.6)
        self.assertEqual(self.feed(["victory"] * 6, start=1.1), [])


class GazeTest(unittest.TestCase):
    CAL = {"DP-1": {"mean": [0.0, 0.6, 0.5, 0.4]}, "DP-2": {"mean": [0.0, 0.35, 0.5, 0.3]},
           "HDMI-A-1": {"mean": [0.35, 0.6, 0.6, 0.4]}}

    def test_head_pose(self):
        yaw, pitch, x, y = G.head_pose(FRONT, SIZE)
        self.assertLess(abs(yaw), 0.2)
        self.assertTrue(0.3 < pitch < 0.9 and 0 < x < 1 and 0 < y < 1)
        self.assertIsNone(G.head_pose(FRONT[:14] + [0.3], SIZE))           # unsure
        self.assertIsNone(G.head_pose(FRONT, (20000, 15000)))               # far behind
        big = list(FRONT)
        small = [v / 3 for v in FRONT[:14]] + [0.95]
        self.assertEqual(G.main_face([small, big], SIZE), G.head_pose(big, SIZE))

    def test_nearest_needs_two_and_a_clear_winner(self):
        self.assertEqual(G.nearest_monitor((0.02, 0.58, 0.5, 0.4), self.CAL), "DP-1")
        self.assertEqual(G.nearest_monitor((0.33, 0.6, 0.6, 0.4), self.CAL), "HDMI-A-1")
        self.assertIsNone(G.nearest_monitor((0.175, 0.6, 0.55, 0.4), self.CAL))    # half way
        self.assertIsNone(G.nearest_monitor((2.0, 0.0, 0.0, 0.0), self.CAL))       # nowhere near
        self.assertIsNone(G.nearest_monitor((0, 0.6, 0.5, 0.4), {"DP-1": self.CAL["DP-1"]}))

    def test_dwell(self):
        g = G.Gaze(self.CAL, dwell_s=1.0)
        got = [g.feed((0.35, 0.6, 0.6, 0.4), i / 10) for i in range(9)]
        self.assertEqual([x for x in got if x], [])                         # not long enough
        got = [g.feed((0.35, 0.6, 0.6, 0.4), 0.9 + i / 10) for i in range(10)]
        self.assertEqual([x for x in got if x], ["HDMI-A-1"])               # once
        self.assertEqual(g.looking, "HDMI-A-1")
        g.feed(None, 3.0)
        g.feed(None, 4.5)
        self.assertIsNone(g.looking)                                         # nobody: forgotten

    def test_calibration(self):
        g = G.Gaze({}, dwell_s=1.0)
        g.start("DP-1", 0.0)
        got = [g.feed((0.01, 0.6, 0.5, 0.4), i / 10) for i in range(31)]
        done = [x for x in got if x]
        self.assertEqual(done[0][:2], ("calibrated", "DP-1"))
        self.assertEqual(done[0][3], 26)                                      # 0.5 s settling skipped
        g.start("DP-2", 10.0)
        got = [g.feed(None, 10 + i / 10) for i in range(31)]
        self.assertEqual([x for x in got if x][0][:2], ("calibration failed", "DP-2"))

    def test_recorded_calibration_and_looks(self):
        with mock.patch.object(G, "CONF", os.path.join(tempfile.mkdtemp(dir=helpers.SCRATCH), "g.json")):
            got = G.replay(os.path.join(FIX, "gaze-calibrate-and-look.jsonl"))
        self.assertEqual([(k, w if isinstance(w, str) else w[:2]) for _t, k, w, _a in got],
                         [("calibration", ("calibrated", "DP-1")), ("calibration", ("calibrated", "DP-2")),
                          ("calibration", ("calibrated", "HDMI-A-1")),
                          ("gaze", "DP-1"), ("gaze", "DP-2"), ("gaze", "HDMI-A-1")])


class Recorded(unittest.TestCase):
    def replay(self, name):
        return [(w, a) for _t, k, w, a in G.replay(os.path.join(FIX, name)) if k == "gesture"]

    def test_sequences(self):
        self.assertEqual(self.replay("gestures-thumbs-up.jsonl"), [("thumbs_up", "confirm")])
        self.assertEqual(self.replay("gestures-thumbs-down.jsonl"), [("thumbs_down", "cancel")])
        self.assertEqual(self.replay("gestures-swipe.jsonl"), [("swipe_right", "workspace-next")])

    def test_nobody_facing_the_screen(self):
        self.assertEqual(self.replay("gestures-thumbs-up-noface.jsonl"), [])


class ActionsTest(unittest.TestCase):
    SHOWN = json.dumps([{"id": 7, "app_name": "Mail", "actions": {"confirm": "x"}},
                        {"id": 9, "app_name": "Voice commands", "actions": {"confirm": "Confirm", "cancel": "Cancel"}}])

    def test_catalog_is_fixed(self):
        for name, (label, what) in G.ACTIONS.items():
            self.assertTrue(label)
            if what:
                self.assertIn(what[0], ("lua", "argv", "bubble"))
        with self.assertRaises(ValueError):
            G.commands("rm -rf ~")
        for g, a in G.DEFAULT_MAP.items():
            self.assertIn(g, G.GESTURES)
            self.assertIn(a, G.ACTIONS)

    def test_confirm_answers_only_the_voice_bubble(self):
        r = Runner({("makoctl", "list"): self.SHOWN})
        self.assertEqual(G.do("confirm", r)[-1], ["makoctl", "invoke", "-n", "9", "confirm"])
        r = Runner({("makoctl", "list"): json.dumps([{"id": 7, "app_name": "Mail", "actions": {"confirm": "x"}}])})
        self.assertEqual(G.do("confirm", r), [])
        self.assertEqual(r.ran("makoctl"), [["makoctl", "list", "-j"]])

    def test_lua_and_argv(self):
        r = Runner()
        self.assertEqual(G.do("workspace-next", r)[0][:2], ["hyprctl", "eval"])
        self.assertIn('"e+1"', r.calls[0][2])
        self.assertEqual(G.do("none", r), [])

    def test_focus_last_window_on_monitor(self):
        mons = json.dumps([{"name": "DP-1", "focused": True, "activeWorkspace": {"id": 3}},
                           {"name": "HDMI-A-1", "focused": False, "activeWorkspace": {"id": 7}}])
        clients = json.dumps([{"address": "0xa", "class": "kitty", "workspace": {"id": 7}, "focusHistoryID": 4},
                              {"address": "0xb", "class": "firefox", "workspace": {"id": 7}, "focusHistoryID": 2},
                              {"address": "0xc", "class": "code", "workspace": {"id": 3}, "focusHistoryID": 0}])
        answers = {("hyprctl", "monitors"): mons, ("hyprctl", "clients"): clients,
                   ("hyprctl", "activewindow"): json.dumps({"fullscreen": 0})}
        r = Runner(answers)
        self.assertEqual(G.focus_on_monitor("HDMI-A-1", r), "focused firefox")
        self.assertIn("address:0xb", r.ran("hyprctl")[-1][2])
        r = Runner(answers)
        self.assertIsNone(G.focus_on_monitor("DP-1", r))                     # already there
        r = Runner({**answers, ("hyprctl", "activewindow"): json.dumps({"fullscreen": 2})})
        self.assertIsNone(G.focus_on_monitor("HDMI-A-1", r))                 # a film / a game
        r = Runner({**answers, ("pidof",): "123"})
        self.assertIsNone(G.focus_on_monitor("HDMI-A-1", r))                 # locked
        self.assertFalse([c for c in r.ran("hyprctl") if c[1] == "eval"])


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class VisionTest(unittest.TestCase):
    def make(self, on=None, conf=None, runner=None):
        self.clock, self.cpu = Clock(), [0.0]
        self.runner = runner or Runner()
        flags = dict({"gestures": True, "gaze": False}, **(on or {}))
        settings = dict(G.load(os.devnull), **(conf or {}))
        return G.Vision(hands=None, settings=lambda: dict(settings), flags=lambda: dict(flags),
                        runner=self.runner, clock=self.clock, cpu=lambda: self.cpu[0])

    def hold(self, v, rec, seconds=1.2):
        out = []
        for _ in range(int(seconds * 10)):
            out += v.process(rec["hands"], [rec["face"]] if rec["face"] else None, SIZE, self.clock.t)
            self.clock.t += 0.1
        return out

    def test_fires_mapped_action_with_feedback(self):
        r = Runner({("makoctl", "list"): ActionsTest.SHOWN})
        v = self.make(runner=r)
        self.assertEqual(self.hold(v, THUMBS), [("gesture", "thumbs_up", "confirm")])
        self.assertIn(["makoctl", "invoke", "-n", "9", "confirm"], r.calls)
        self.assertTrue(r.ran("notify-send"))

    def test_locked_or_unmapped_does_nothing(self):
        r = Runner({("pidof",): "4242", ("makoctl", "list"): ActionsTest.SHOWN})
        v = self.make(runner=r)
        self.hold(v, THUMBS)
        self.assertFalse([c for c in r.calls if c[:2] == ["makoctl", "invoke"]])
        r = Runner()
        v = self.make(runner=r, conf={"map_thumbs_up": "none", "feedback": "off"})
        self.hold(v, THUMBS)
        self.assertEqual(r.calls, [])

    def test_off_means_nothing(self):
        v = self.make(on={"gestures": False})
        self.assertFalse(v.active)
        self.assertEqual(self.hold(v, THUMBS), [])
        self.assertIsNone(v.frame_size)
        self.assertEqual(self.make().frame_size, G.HAND_FRAME)

    def test_cpu_budget_lowers_fps(self):
        v = self.make(conf={"fps": 12, "cpu": 30})
        self.assertEqual(v.fps(), 12)
        v.cost = 0.05                       # 50 ms a frame: 30 % allows 6 a second
        self.assertAlmostEqual(v.fps(), 6.0)
        v.cost = 1.0
        self.assertEqual(v.fps(), G.MIN_FPS)

    def test_calibrate_needs_gaze(self):
        v = self.make()
        v.control("calibrate DP-1")
        self.assertEqual(v.calibration_msg["state"], "failed")
        v = self.make(on={"gaze": True})
        v.control("calibrate DP-1")
        self.assertEqual(v.calibration_msg["state"], "looking")
        self.assertEqual(json.loads(json.dumps(v.live()))["calibration"]["state"], "looking")


    def test_broken_hand_model_is_said_once_and_the_rest_goes_on(self):
        v = self.make(on={"gaze": True})
        calls = []

        class Broken:
            def __call__(self, _frame):
                calls.append(1)
                raise RuntimeError("cv2.error: can't read onnx")

        class Frame:
            shape = (480, 640, 3)
        v.hands = Broken()
        v.frame(Frame(), [FRONT], SIZE)
        v.frame(Frame(), [FRONT], SIZE)
        self.assertEqual(len(calls), 1)                 # not retried every frame
        self.assertIn("did not load", v.live()["error"])
        v.flags = lambda: {"gestures": False, "gaze": True}
        v.refresh()                                     # off and on again retries
        self.assertIsNone(v.live()["error"])

    def test_gaze_off_ends_a_calibration(self):
        flags = {"gestures": False, "gaze": True}
        v = self.make(on=flags)
        v.control("calibrate DP-1")
        v.flags = lambda: {"gestures": False, "gaze": False}
        v.refresh()
        self.assertIsNone(v.gaze.calibrating)
        self.assertEqual(v.calibration_msg["state"], "failed")


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(dir=helpers.SCRATCH), "gestures.json")

    def test_defaults_check_and_save(self):
        self.assertEqual(G.load(self.path)["map_open_palm"], "overview")
        G.save("map_fist", "play-pause", self.path)
        G.save("fps", 12, self.path)
        conf = G.load(self.path)
        self.assertEqual((conf["map_fist"], conf["fps"]), ("play-pause", 12))
        for key, value in (("fps", 30), ("map_fist", "shell"), ("gaze_focus", "maybe"), ("nope", 1)):
            with self.assertRaises(ValueError):
                G.save(key, value, self.path)
        with open(self.path) as handle:
            self.assertEqual(json.load(handle), {"map_fist": "play-pause", "fps": 12})

    def test_calibration_store(self):
        G.save_calibration("DP-1", [0.1, 0.5, 0.5, 0.4], 20, self.path)
        G.save_calibration("DP-2", [0.0, 0.3, 0.5, 0.3], 20, self.path)
        self.assertEqual(sorted(G.load(self.path)["calibration"]), ["DP-1", "DP-2"])
        G.forget("DP-1", self.path)
        self.assertEqual(list(G.load(self.path)["calibration"]), ["DP-2"])
        with self.assertRaises(ValueError):
            G.forget("DP-1", self.path)
        G.forget("all", self.path)
        self.assertEqual(G.load(self.path)["calibration"], {})
        with open(self.path, "w") as handle:
            json.dump({"calibration": {"X": {"mean": "junk"}}, "fps": 99}, handle)
        self.assertEqual((G.load(self.path)["calibration"], G.load(self.path)["fps"]), ({}, 10))


class PrivacySwitches(unittest.TestCase):
    def test_off_as_shipped(self):
        conf = dict(privacy_settings.DEFAULTS)
        self.assertFalse(privacy_settings.gestures_on(conf) or privacy_settings.gaze_on(conf))
        self.assertFalse(privacy_settings.camera_wanted(conf))
        self.assertTrue(privacy_settings.camera_wanted(dict(conf, gaze="on")))

    def test_service_follows_any_switch(self):
        path = os.path.join(tempfile.mkdtemp(dir=helpers.SCRATCH), "privacy.conf")
        with mock.patch.object(privacy_settings, "CONF", path), \
                mock.patch.object(privacy_settings, "run_ok", return_value=(True, "")) as run_ok:
            privacy_settings.cmd_camera("gestures", True)
            run_ok.assert_called_with("systemctl", "--user", "enable", "--now", privacy_settings.PRESENCE_UNIT)
            privacy_settings.cmd_presence(False)            # presence off: gestures still need it
            run_ok.assert_called_with("systemctl", "--user", "enable", "--now", privacy_settings.PRESENCE_UNIT)
            privacy_settings.cmd_camera("gestures", False)
            run_ok.assert_called_with("systemctl", "--user", "disable", "--now", privacy_settings.PRESENCE_UNIT)


class FakeVision:
    def __init__(self):
        self.active, self.frames, self.refreshed, self.msgs = True, 0, 0, []
        self.frame_size = G.HAND_FRAME

    def refresh(self):
        self.refreshed += 1

    def fps(self):
        return 10

    def frame(self, frame, faces, size):
        self.frames += 1

    def control(self, msg):
        self.msgs.append(msg)

    def live(self):
        return {"fps": 10}


class FakeCamera:
    dev = "/dev/video9"

    def __init__(self):
        self.is_open, self.opens, self.size = False, 0, P.FRAME

    def frame(self):
        if not self.is_open:
            self.opens += 1
        self.is_open = True
        return "frame"

    def release(self):
        self.is_open = False


class WatcherWithVision(unittest.TestCase):
    def setUp(self):
        self.clock, self.cam, self.vision = Clock(), FakeCamera(), FakeVision()
        self.events, self.on = [], False                   # presence itself switched off
        self.w = P.Watcher(camera=self.cam, detector=lambda f: (True, True), actions=self, clock=self.clock,
                           busy=lambda: [], gaming=lambda: False, enabled=lambda: self.on,
                           settings=lambda: P.load(os.devnull), vision=self.vision)

    def away(self, conf):
        self.events.append("away")
        return []

    def back(self, conf):
        self.events.append("back")
        return []

    def spin(self, seconds):
        end = self.clock.t + seconds
        while self.clock.t < end:
            if not self.w.checks():
                return False
            self.clock.t += self.w.step()
        return True

    def test_calibrate_rereads_the_switches_first(self):
        before = self.vision.refreshed
        self.w.control("calibrate DP-1")
        self.assertEqual(self.vision.refreshed, before + 1)     # gaze switched on a moment ago counts
        self.assertEqual(self.vision.msgs, ["calibrate DP-1"])

    def test_vision_alone_keeps_the_camera_and_looks_faster(self):
        self.assertTrue(self.spin(3))
        self.assertTrue(self.cam.is_open)
        self.assertGreaterEqual(self.vision.frames, 25)      # 10 a second, not 1
        self.assertEqual(self.cam.size, G.HAND_FRAME)
        self.w.control("idle off")
        self.w.control("calibrate DP-1")
        self.assertEqual(self.vision.msgs, ["calibrate DP-1"])
        self.assertIn("vision", self.w.live())

    def test_presence_off_means_no_away_actions(self):
        self.w.control("idle on")
        self.w.detector = lambda f: (False, False)
        self.spin(120)
        self.assertEqual(self.events, [])

    def test_both_off_stops_and_vision_off_slows(self):
        self.vision.active = False
        self.w.next_check = 0
        self.assertFalse(self.w.checks())
        self.on = True
        self.w.next_check = 0
        self.assertTrue(self.w.checks())
        self.assertEqual(self.cam.size, P.FRAME)
        frames = self.vision.frames
        self.spin(3)
        self.assertEqual(self.vision.frames, frames)          # not handed frames while off


class PageText(unittest.TestCase):
    def setUp(self):
        import importlib
        try:
            self.page = importlib.import_module("settings_pages.gestures")
        except (ImportError, ValueError) as exc:      # no GTK in this python
            self.skipTest(str(exc))

    def test_status(self):
        base = {"switches": {"gestures": False, "gaze": False}}
        self.assertTrue(self.page.status_text(base).startswith("Off."))
        on = {"switches": {"gestures": True, "gaze": True}, "installed": {"venv": True}, "service": "active",
              "camera": True, "live": {"fps": 10, "cpu_ms": 12.3, "holding": ["thumbs_up", 0.5],
                                       "looking_at": "DP-2"}}
        text = self.page.status_text(on)
        self.assertIn("holding thumbs up 50 %", text)
        self.assertIn("looking at DP-2", text)
        self.assertIn("paused", self.page.status_text(dict(on, camera=False, why="paused")))
        broken = dict(on, live=dict(on["live"], error="the hand models did not load or run: x"))
        self.assertIn("Gestures stopped", self.page.status_text(broken))
        self.assertIn("calibrate at least two", self.page.gaze_hint(["DP-1", "DP-2"], {"DP-1": {}}))
        self.assertEqual(self.page.calibration_text("DP-1", {"DP-1": {"n": 20}}), "calibrated (20 looks)")


if __name__ == "__main__":
    unittest.main()
