"""scripts/presence.py (the webcam presence check): what counts as a face
turned to the screen, the away / back state machine, the actions (never an
unlock, never undoing what it did not do), the watcher's camera discipline
(released when paused, in gamemode, while another app uses it, between
bursts while away), the settings and the sysfs camera list; plus
privacy_settings' master switch (off as shipped) and the page's wording.

Hermetic: no camera, no OpenCV (the detector and camera are fakes), no
playerctl / makoctl / loginctl / hyprctl (a recording runner), settings in
helpers.py's scratch XDG_STATE_HOME. The real detector is tried on photos by
hand: `presence.py test-image FILE` in its venv."""
import os
import tempfile
import unittest

import helpers

P = helpers.import_script("presence.py")
P.log = lambda *_a, **_k: None
import privacy_settings  # noqa: E402

# a YuNet row: x y w h, right eye, left eye, nose, mouth corners, score
FRONT = [100, 60, 80, 100, 120, 100, 160, 100, 140, 120, 125, 140, 155, 140, 0.95]
TURNED = [100, 60, 80, 100, 120, 100, 160, 100, 168, 120, 125, 140, 155, 140, 0.95]
TINY = [100, 60, 10, 12, 102, 64, 108, 64, 105, 67, 103, 70, 107, 70, 0.95]


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class Faces(unittest.TestCase):
    def test_facing(self):
        self.assertEqual(P.facing(FRONT, 320), (True, True))
        self.assertEqual(P.facing(TURNED, 320), (True, False))      # here, but looking away
        self.assertEqual(P.facing(TINY, 320), (False, False))       # someone far behind
        low = FRONT[:14] + [0.5]
        self.assertEqual(P.facing(low, 320), (False, False))
        tilted = FRONT[:]
        tilted[7] = 140                                             # one eye far below the other
        self.assertEqual(P.facing(tilted, 320), (True, False))

    def test_boxes(self):
        found = P.boxes([FRONT, TURNED, TINY], (320, 240))
        self.assertEqual([(b["here"], b["facing"]) for b in found], [(True, True), (True, False), (False, False)])
        self.assertTrue(all(0 <= b[k] <= 1 for b in found for k in "xywh"))
        self.assertEqual(P.boxes(None, (320, 240)), [])

    def test_judge(self):
        self.assertEqual(P.judge(None, 320), (False, False))
        self.assertEqual(P.judge([TURNED, FRONT], 320), (True, True))


class States(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.p = P.Presence(60, self.clock)

    def test_no_lock_while_typing(self):
        self.clock.t += 600
        self.assertIsNone(self.p.feed(False, False))                # input not idle: never away
        self.p.input(True)
        self.clock.t += 10
        self.assertIsNone(self.p.feed(False, False))                # idle, but only 10 s without a face
        self.clock.t += 51
        self.assertEqual(self.p.feed(False, False), "away")

    def test_profile_keeps_you_here_and_back_needs_facing(self):
        self.p.input(True)
        for _ in range(10):
            self.clock.t += 20
            self.assertIsNone(self.p.feed(True, False))             # a face in profile: still here
        self.clock.t += 61
        self.assertEqual(self.p.feed(False, False), "away")
        self.assertIsNone(self.p.feed(True, False))                 # someone walks past sideways
        self.assertIsNone(self.p.feed(True, True))
        self.assertIsNone(self.p.feed(False, False))                # the streak breaks
        self.assertIsNone(self.p.feed(True, True))
        self.assertEqual(self.p.feed(True, True), "back")

    def test_input_is_back(self):
        self.p.input(True)
        self.clock.t += 61
        self.assertEqual(self.p.feed(False, False), "away")
        self.assertEqual(self.p.input(False), "back")


class Runner:
    def __init__(self, playing=("mpv",), dnd=False, locked=False, dpms_off=True):
        self.calls, self.playing, self.dnd, self.locked, self.dpms_off = [], set(playing), dnd, locked, dpms_off

    def __call__(self, *cmd, timeout=5):
        self.calls.append(cmd)
        if cmd[:2] == ("playerctl", "-l"):
            return "mpv\nfirefox\n"
        if cmd[0] == "playerctl" and cmd[-1] == "status":
            return "Playing\n" if cmd[2] in self.playing else "Paused\n"
        if cmd[0] == "playerctl" and cmd[-1] == "pause":
            self.playing.discard(cmd[2])
        if cmd[:2] == ("makoctl", "mode") and len(cmd) == 2:
            return "default do-not-disturb\n" if self.dnd else "default\n"
        if cmd[:3] == ("makoctl", "mode", "-a"):
            self.dnd = True
        if cmd[:3] == ("makoctl", "mode", "-r"):
            self.dnd = False
        if cmd[0] == "pidof":
            return "123\n" if self.locked else ""
        if cmd[:2] == ("hyprctl", "monitors"):
            return '[{"dpmsStatus": %s}]' % ("false" if self.dpms_off else "true")
        return ""


class ActionsTest(unittest.TestCase):
    def setUp(self):
        P.poke_automations, self.real_poke = (lambda e: self.pokes.append(e)), P.poke_automations
        self.pokes = []
        self.conf = dict(P.load(os.devnull), dnd="on")

    def tearDown(self):
        P.poke_automations = self.real_poke

    def test_away_and_back(self):
        r = Runner()
        a = P.Actions(r)
        done = a.away(self.conf)
        self.assertIn(("playerctl", "-p", "mpv", "pause"), r.calls)
        self.assertNotIn(("playerctl", "-p", "firefox", "pause"), r.calls)  # it was not playing
        self.assertIn(("loginctl", "lock-session"), r.calls)
        self.assertEqual(r.calls[-1], ("loginctl", "lock-session"))         # the lock comes last
        self.assertIn("locked", done)
        a.back(self.conf)
        self.assertIn(("playerctl", "-p", "mpv", "play"), r.calls)
        self.assertNotIn(("playerctl", "-p", "firefox", "play"), r.calls)
        self.assertIn(("hyprctl", "dispatch", "hl.dsp.dpms({ on = true })"), r.calls)
        self.assertFalse(any("unlock" in " ".join(c) or "pkill" in c[0] or c[0] == "kill" for c in r.calls))
        self.assertFalse(r.dnd)
        self.assertEqual(self.pokes, ["presence-away", "presence-back"])

    def test_never_fights(self):
        r = Runner(dnd=True, locked=True, dpms_off=False)
        a = P.Actions(r)
        a.away(self.conf)
        self.assertNotIn(("loginctl", "lock-session"), r.calls)              # already locked
        a.back(self.conf)
        self.assertTrue(r.dnd)                                               # it was yours: left on
        self.assertFalse(any(c[:2] == ("hyprctl", "dispatch") for c in r.calls))   # screens were on

    def test_switched_off_actions(self):
        r = Runner()
        conf = {k: "off" for k in P.ACTIONS}
        P.Actions(r).away(conf)
        P.Actions(r).back(conf)
        self.assertEqual([c for c in r.calls if c[0] != "hyprctl"], [])
        self.assertEqual(self.pokes, [])


class FakeCamera:
    dev = "/dev/video9"

    def __init__(self):
        self.is_open, self.opens, self.fail = False, 0, False

    def frame(self):
        if self.fail:
            return None
        if not self.is_open:
            self.opens += 1
        self.is_open = True
        return "frame"

    def release(self):
        self.is_open = False


class WatcherTest(unittest.TestCase):
    def setUp(self):
        self.clock, self.cam, self.seen = Clock(), FakeCamera(), [(True, True)]
        self.events, self.users, self.gaming, self.on = [], [], False, True
        self.w = P.Watcher(camera=self.cam, detector=lambda f: self.seen[0], actions=self, clock=self.clock,
                           busy=lambda: self.users, gaming=lambda: self.gaming, enabled=lambda: self.on,
                           settings=lambda: dict(P.load(os.devnull), away_s=30))

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

    def test_away_back_and_bursts(self):
        self.w.control("idle on")
        self.spin(5)
        self.assertTrue(self.cam.is_open)                       # present: held open at 1 fps
        self.seen[0] = (False, False)
        self.spin(40)
        self.assertEqual(self.events, ["away"])
        opens = self.cam.opens
        self.spin(20)
        self.assertFalse(self.cam.is_open)                      # released between bursts
        self.assertGreaterEqual(self.cam.opens - opens, 3)
        self.seen[0] = (True, True)
        self.spin(10)
        self.assertEqual(self.events, ["away", "back"])

    def test_watch_looks_faster_for_a_while(self):
        self.assertAlmostEqual(self.w.step(), 1.0)
        self.w.control("watch")
        self.assertAlmostEqual(self.w.step(), 1.0 / P.WATCH_FPS)
        self.assertTrue(self.w.live()["watched"])
        self.assertTrue(self.w.live()["look"]["facing"])
        self.clock.t += P.WATCH_S + 1
        self.assertAlmostEqual(self.w.step(), 1.0)
        self.assertFalse(self.w.live()["watched"])

    def test_long_away_stops_looking(self):
        self.w.control("idle on")
        self.seen[0] = (False, False)
        self.spin(40)
        self.spin(P.LONG_AWAY_S + 10)
        opens = self.cam.opens
        self.spin(60)
        self.assertEqual(self.cam.opens, opens)
        self.assertIn("long time", self.w.needed())
        self.w.control("idle off")                              # the keyboard: back, camera again
        self.assertEqual(self.events[-1], "back")
        self.spin(3)
        self.assertTrue(self.cam.is_open)

    def test_released_for_gamemode_calls_and_pause(self):
        self.spin(3)
        self.assertTrue(self.cam.is_open)
        self.users = ["zoom"]
        self.spin(P.CHECK_S + 1)
        self.assertFalse(self.cam.is_open)
        self.assertIn("zoom", self.w.needed())
        self.users, self.gaming = [], True
        self.spin(P.CHECK_S + 1)
        self.assertEqual((self.cam.is_open, self.w.needed()), (False, "gamemode"))
        self.gaming = False
        self.spin(P.CHECK_S + 1)
        self.assertTrue(self.cam.is_open)
        self.w.control("pause 5")
        self.spin(2)
        self.assertFalse(self.cam.is_open)
        self.w.control("resume")
        self.spin(2)
        self.assertTrue(self.cam.is_open)

    def test_no_events_while_paused_and_stops_when_switched_off(self):
        self.w.control("idle on")
        self.w.control("pause 60")
        self.seen[0] = (False, False)
        self.spin(120)
        self.assertEqual((self.events, self.cam.opens), ([], 0))
        self.on = False
        self.w.next_check = 0
        self.assertFalse(self.w.checks())

    def test_broken_camera_waits(self):
        self.cam.fail = True
        self.spin(5)
        self.assertGreater(self.w.retry_at, self.clock.t)
        self.assertTrue(self.w.warned)                          # said once, not every RETRY_S

    def test_another_camera_picked_on_the_page(self):
        self.cam.devices = ["/dev/video1"]
        self.spin(2)
        self.assertTrue(self.cam.is_open)
        self.w.settings = lambda: dict(P.load(os.devnull), away_s=30, camera="/dev/video7")
        self.w.control("reload")
        self.w.checks()
        self.assertEqual(self.cam.devices, ["/dev/video7"])
        self.assertFalse(self.cam.is_open)                      # let go of the old one


class SettingsAndCameras(unittest.TestCase):
    def test_settings(self):
        path = os.path.join(tempfile.mkdtemp(dir=helpers.SCRATCH), "presence.json")
        self.assertEqual(P.load(path)["lock"], "on")
        P.save("away_s", "120", path)
        P.save("dnd", "ON", path)
        self.assertEqual((P.load(path)["away_s"], P.load(path)["dnd"]), (120, "on"))
        for key, bad in (("away_s", "5"), ("fps", "10"), ("lock", "maybe"), ("nope", "1")):
            with self.assertRaises(ValueError):
                P.save(key, bad, path)

    def test_cameras_from_sysfs(self):
        root = tempfile.mkdtemp(dir=helpers.SCRATCH)
        for node, name, index, usb in (("video0", "Intel MIPI Camera", "0", False),
                                       ("video1", "HD Webcam C525", "0", True),
                                       ("video2", "HD Webcam C525", "1", True)):
            base = os.path.join(root, node)
            dev = os.path.join(root, "devices", "pci0", "usb1" if usb else "ipu", node)
            os.makedirs(dev)
            os.makedirs(base)
            os.symlink(dev, os.path.join(base, "device"))
            for f, text in (("name", name + "\n"), ("index", index + "\n")):
                with open(os.path.join(base, f), "w") as handle:
                    handle.write(text)
        real, P.SYSFS = P.SYSFS, root
        try:
            found = P.cameras()
        finally:
            P.SYSFS = real
        self.assertEqual([c["dev"] for c in found], ["/dev/video1", "/dev/video0"])   # USB first, no metadata node
        self.assertEqual(P.pick_cameras("c525", found), ["/dev/video1"])
        self.assertEqual(P.pick_cameras("/dev/video4", found), ["/dev/video4"])


class MasterSwitch(unittest.TestCase):
    def test_off_as_shipped(self):
        self.assertEqual(privacy_settings.DEFAULTS["presence"], "off")
        self.assertFalse(privacy_settings.presence_on(privacy_settings.parse_conf("")))
        self.assertTrue(privacy_settings.presence_on(privacy_settings.parse_conf("presence=on\n")))


class PageWords(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from settings_pages import presence as page
        except Exception as exc:   # noqa: BLE001
            raise unittest.SkipTest(f"settings_pages.presence not importable: {exc}")
        cls.page = page

    def test_status_text(self):
        base = {"on": True, "installed": {"venv": True, "model": True}, "service": "active",
                "settings": {"fps": 1}}
        self.assertTrue(self.page.status_text({"on": False}).startswith("Off: nothing opens"))
        self.assertIn("stays open for gestures and gaze",
                      self.page.status_text({"on": False, "gestures": True, "gaze": True}))
        self.assertIn("service is failed", self.page.status_text(dict(base, service="failed")))
        live = {"state": "away", "camera": False, "why": "gamemode", "paused_for": 0}
        self.assertEqual(self.page.status_text(dict(base, live=live)),
                         "you are away  ·  the camera is closed: gamemode")
        live = {"state": "present", "camera": True, "device": "/dev/video1", "paused_for": 0}
        self.assertIn("open (/dev/video1)", self.page.status_text(dict(base, live=live)))

    def test_live_text(self):
        import time as _t
        on = {"on": True}
        self.assertEqual(self.page.live_text({"on": False}, None)[0], "Not watching")
        self.assertEqual(self.page.live_text(on, {"paused_for": 600})[0], "Paused")
        self.assertEqual(self.page.live_text(on, {"why": "gamemode", "camera": False})[:2],
                         ("Camera closed", "gamemode"))
        face = {"x": .1, "y": .2, "w": .3, "h": .4, "score": .93, "here": True, "facing": True}
        live = {"camera": True, "state": "present", "watched": True,
                "look": {"here": True, "facing": True, "at": _t.time(), "faces": [face]}}
        head, detail, kind = self.page.live_text(on, live)
        self.assertEqual((head, kind), ("I see you, facing the screen", "facing"))
        self.assertIn("1 face, 93% sure", detail)
        live["look"] = {"here": False, "facing": False, "at": _t.time() - 30, "faces": []}
        head, _detail, kind = self.page.live_text(on, live)
        self.assertEqual((head, kind), ("Last look: nobody in view", "unsure"))
        self.assertAlmostEqual(self.page.mirrored(face)[0], 0.6)

    def test_camera_items(self):
        items = self.page.camera_items([{"dev": "/dev/video1", "name": "C525"}], "/dev/video7")
        self.assertEqual([k for k, _ in items], ["auto", "/dev/video1", "/dev/video7"])


if __name__ == "__main__":
    unittest.main()
