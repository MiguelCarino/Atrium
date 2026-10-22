"""scripts/ambient.py (the ambient desktop): the settings and their checks
(local-only addresses, entity ids), the 0600 secrets and their redaction,
the part of the day, the weather, the mood's priorities, the plan per output,
the accent tint, the Applier (dry runs write nothing; real runs write only
the runtime files, each once; lights only on a mood change, again after a
failure), the Hue / Home Assistant requests (pairing through error 101, a fake
Home Assistant on 127.0.0.1), nightlight.sh's nudge, theme-from-wallpaper's
hook, a rendered soundscape, and the page's wording.

Hermetic: helpers.py's scratch XDG dirs; every hyprctl / makoctl / systemctl /
nightlight.sh call goes through a stubbed run(); nothing is played, shown or
sent off this machine (the only server is a thread on 127.0.0.1)."""
import datetime as dt
import http.server
import json
import os
import shutil
import stat
import subprocess
import tempfile
import threading
import unittest

import helpers

A = helpers.import_script("ambient.py")
A.log = lambda *_a, **_k: None

LAN = lambda *_a: [(2, 1, 6, "", ("192.168.1.10", 0))]     # noqa: E731
CLOUD = lambda *_a: [(2, 1, 6, "", ("52.1.2.3", 0))]       # noqa: E731
KINDS = {"sun": {113}, "cloud": {119, 122}, "rain": {296}, "storm": {200}}


def values(**over):
    v = dict(A.DEFAULTS)
    v.update(over)
    return v


class Settings(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(dir=helpers.SCRATCH), "ambient.conf")

    def test_defaults_ship_off(self):
        v = A.read_settings(self.path)
        self.assertEqual(v["enabled"], "off")
        self.assertEqual(v["lights"], "off")
        self.assertEqual(v["soundscape"], "off")
        self.assertEqual(v["theme"], "off")          # never switches the theme unless asked

    def test_write_and_bad_lines(self):
        A.write_setting("vol_focus", "25", self.path)
        with open(self.path, "a") as fh:
            fh.write("vol_night=999\nstrength=loud\nnonsense\n")
        v = A.read_settings(self.path)
        self.assertEqual(v["vol_focus"], "25")
        self.assertEqual(v["vol_night"], "40")       # out of range: the default
        self.assertEqual(v["strength"], "subtle")
        with self.assertRaises(ValueError):
            A.write_setting("sound_volume", "90", self.path)
        with self.assertRaises(ValueError):
            A.write_setting("nope", "1", self.path)

    def test_entities_and_scenes(self):
        self.assertEqual(A.check_value("ha_lights", " light.desk ,light.lamp "), "light.desk,light.lamp")
        with self.assertRaises(ValueError):
            A.check_value("ha_lights", "switch.heater")
        with self.assertRaises(ValueError):
            A.check_value("ha_lights", "light.desk; rm -rf /")
        self.assertEqual(A.parse_scenes("focus=scene.work, night=scene.sleep"),
                         {"focus": "scene.work", "night": "scene.sleep"})
        with self.assertRaises(ValueError):
            A.parse_scenes("party=scene.x")

    def test_local_only(self):
        self.assertTrue(A.private_ip("192.168.1.20"))
        self.assertTrue(A.private_ip("127.0.0.1"))
        self.assertFalse(A.private_ip("8.8.8.8"))
        self.assertEqual(A.check_url("http://homeassistant.local:8123/", resolve=LAN),
                         "http://homeassistant.local:8123")
        for bad in ("https://abc.ui.nabu.casa", "ftp://192.168.1.2", "http://192.168.1.2/api?x=1",
                    "http://user@192.168.1.2"):
            with self.assertRaises(ValueError):
                A.check_url(bad, resolve=CLOUD)
        with self.assertRaises(ValueError):
            A.check_value("hue_bridge", "8.8.8.8")
        with self.assertRaises(ValueError):
            A.http("GET", "http://8.8.8.8/api", dry=True)    # refused even as a dry run


class Secrets(unittest.TestCase):
    def test_mode_and_redaction(self):
        path = os.path.join(tempfile.mkdtemp(dir=helpers.SCRATCH), "s.json")
        A.write_secret("ha_token", "eyJhbGciOiJIUzI1NiJ9.secret-token", path)
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        secrets = A.read_secrets(path)
        self.assertEqual(A.redact("Bearer eyJhbGciOiJIUzI1NiJ9.secret-token failed", secrets), "Bearer *** failed")
        A.write_secret("ha_token", "", path)
        self.assertEqual(A.read_secrets(path), {})


class Time(unittest.TestCase):
    def at(self, h, m=0, **kw):
        return A.part_of_day(dt.datetime(2026, 10, 20, h, m), (20, 0), (7, 0), **kw)

    def test_parts(self):
        self.assertEqual(self.at(12), "day")
        self.assertEqual(self.at(21), "night")
        self.assertEqual(self.at(2), "late")
        self.assertEqual(self.at(6), "night")
        self.assertEqual(self.at(18, 30, sunset=dt.time(18, 10)), "evening")
        self.assertEqual(self.at(18, 0, sunset=dt.time(18, 10)), "day")
        self.assertEqual(self.at(17, 30, evening_from=(17, 0)), "evening")
        self.assertEqual(self.at(8, sunset=dt.time(18, 10)), "day")      # the morning is no evening

    def test_weather(self):
        data = {"current_condition": [{"weatherCode": "296"}],
                "weather": [{"astronomy": [{"sunrise": "07:33 AM", "sunset": "07:09 PM"}]}]}
        self.assertEqual(A.weather(data, KINDS), ("rain", dt.time(7, 33), dt.time(19, 9)))
        self.assertEqual(A.weather(None, KINDS), (None, None, None))

    def test_focus_running(self):
        path = os.path.join(tempfile.mkdtemp(dir=helpers.SCRATCH), "timers.json")
        with open(path, "w") as fh:
            json.dump({"timers": [{"kind": "focus", "due": 2000}, {"kind": "timer", "due": 9999}]}, fh)
        self.assertTrue(A.focus_running(1000, path))
        self.assertFalse(A.focus_running(3000, path))


class Mood(unittest.TestCase):
    def test_priorities(self):
        v = values()
        self.assertEqual(A.mood_of({"away": True, "focus": True, "presence": "away"}, v)[0], "away")
        self.assertEqual(A.mood_of({"focus": True, "part": "late"}, v)[0], "focus")
        self.assertEqual(A.mood_of({"dnd": True, "part": "day"}, v)[0], "day")
        self.assertEqual(A.mood_of({"dnd": True, "part": "day"}, values(dnd_focus="on"))[0], "focus")
        self.assertEqual(A.mood_of({"part": "late"}, v)[0], "night")
        self.assertEqual(A.mood_of({"part": "evening"}, v)[0], "relax")


class Plan(unittest.TestCase):
    def test_off_outputs_are_absent(self):
        p = A.plan({"part": "day"}, values(wallpaper="off", accent="off", nightlight="off", animations="off",
                                           notify="off"))
        for key in A.OUTPUTS:
            self.assertNotIn(key, p)

    def test_focus(self):
        p = A.plan({"part": "day", "focus": True}, values(soundscape="on"))
        self.assertEqual(p["mood"], "focus")
        self.assertEqual(p["notify"], 30)
        self.assertEqual(p["animations"], 1)
        self.assertEqual(p["nightlight"], 400)
        self.assertLess(p["accent"], 0)
        self.assertEqual(p["soundscape"], {"kind": "rain", "volume": 20})
        self.assertEqual(A.plan({"part": "day", "focus": True}, values(anim_style="still"))["animations"], 2)
        self.assertEqual(A.plan({"part": "day", "focus": True}, values(anim_when="night"))["animations"], 0)

    def test_clear_day_is_no_change(self):
        p = A.plan({"part": "day", "weather": "sun"}, values())
        self.assertEqual(p["wallpaper"][3], 0)
        self.assertEqual(p["accent"], 0)
        self.assertEqual(p["notify"], 100)
        self.assertEqual(p["nightlight"], 0)

    def test_strength_and_caps(self):
        subtle = A.plan({"part": "late"}, values())["wallpaper"][3]
        medium = A.plan({"part": "late"}, values(strength="medium"))["wallpaper"][3]
        self.assertGreater(medium, subtle)
        self.assertLessEqual(medium, A.VEIL_MAX)
        self.assertEqual(A.plan({"part": "late"}, values())["nightlight"], -400)
        self.assertEqual(A.plan({"part": "late"}, values(strength="medium"))["nightlight"], -650)

    def test_soundscape_holds(self):
        v = values(soundscape="on")
        self.assertEqual(A.plan({"focus": True, "music": True}, v)["soundscape"], "")
        self.assertEqual(A.plan({"focus": True, "music": True}, values(soundscape="on", sound_music="keep"))
                         ["soundscape"]["kind"], "rain")
        self.assertEqual(A.plan({"focus": True, "gamemode": True}, v)["soundscape"], "")
        self.assertEqual(A.plan({"part": "evening"}, v)["soundscape"], "")
        self.assertTrue(A.plan({"part": "evening"}, values(soundscape="on", sound_when="relax"))["soundscape"])
        self.assertTrue(A.plan({"part": "day", "soundscape_now": True}, values())["soundscape"])
        w = A.plan({"focus": True, "weather": "storm"}, values(soundscape="on", sound_kind="weather"))
        self.assertEqual(w["soundscape"]["kind"], "rain")
        w = A.plan({"focus": True, "weather": "sun"}, values(soundscape="on", sound_kind="weather"))
        self.assertEqual(w["soundscape"]["kind"], "brown")

    def test_lights(self):
        v = values(lights="hue")
        self.assertEqual(A.plan({"part": "day", "focus": True}, v)["lights"]["kelvin"], 5000)
        self.assertEqual(A.plan({"away": True}, v)["lights"], {"on": False})
        self.assertIsNone(A.plan({"away": True}, values(lights="hue", lights_away="off"))["lights"])
        self.assertEqual(A.plan({"part": "day", "weather": "rain"}, v)["lights"]["bri"], 90)
        s = A.plan({"part": "late"}, values(lights="ha", ha_scenes="night=scene.sleep"))["lights"]
        self.assertEqual(s["scene"], "scene.sleep")

    def test_theme_follows(self):
        orig = A.schedule
        A.schedule = lambda: type("S", (), {"picks": staticmethod(lambda: {"day": "aero", "evening": "",
                                                                            "night": "matrix"})})
        try:
            v = values(theme="on", focus_theme="moe")
            self.assertEqual(A.plan({"part": "day"}, v)["theme"], "aero")
            self.assertEqual(A.plan({"part": "late"}, v)["theme"], "matrix")
            self.assertEqual(A.plan({"part": "evening"}, v)["theme"], "aero")     # no evening pick: the day's
            self.assertEqual(A.plan({"part": "day", "focus": True}, v)["theme"], "moe")
            self.assertEqual(A.plan({"part": "day", "focus": True}, v, themes=["aero"])["theme"], "")  # gone
            self.assertEqual(A.plan({"away": True}, v)["theme"], "")
        finally:
            A.schedule = orig

    def test_describe(self):
        lines = A.describe(A.plan({"part": "late"}, values(lights="hue")))
        self.assertTrue(lines[0].startswith("mood: night"))
        self.assertIn("lights: 25% at 2200 K", lines)


class Tint(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(dir=helpers.SCRATCH), "accent.conf")

    def hue(self, hexc):
        import colorsys
        return colorsys.rgb_to_hsv(*(int(hexc[i:i + 2], 16) / 255 for i in (1, 3, 5)))[0] * 360

    def test_no_file_is_unchanged(self):
        self.assertEqual(A.tinted("#3ddc68", self.path), "#3ddc68")

    def test_warm_and_cool_are_subtle(self):
        with open(self.path, "w") as fh:
            fh.write("warmth=1\narc=0.12\n")
        warm = A.tinted("#3ddc68", self.path)
        self.assertLess(self.hue(warm), self.hue("#3ddc68"))                 # towards amber
        self.assertLess(self.hue("#3ddc68") - self.hue(warm), 15)
        with open(self.path, "w") as fh:
            fh.write("warmth=-1\narc=0.12\n")
        cool = A.tinted("#3ddc68", self.path)
        self.assertGreater(self.hue(cool), self.hue("#3ddc68"))              # towards blue
        self.assertEqual(A.tinted("#808080", self.path), "#808080")           # grey has no hue to move
        self.assertEqual(A.tinted("", self.path), "")

    def test_theme_from_wallpaper_hook(self):
        T = helpers.import_script("theme-from-wallpaper.py")
        self.assertEqual(T.ambient_tint("#3ddc68"), "#3ddc68")               # ambient off: untouched
        try:
            A.write_file(A.ACCENT_FILE, "warmth=0.8\narc=0.12\n")
            self.assertNotEqual(T.ambient_tint("#3ddc68"), "#3ddc68")
            self.assertNotEqual(T.ambient_tint(None), None)                  # the base neon, tinted
        finally:
            A.remove(A.ACCENT_FILE)


class Recorder:
    def __init__(self, rc=0, stdout=""):
        self.calls, self.rc, self.stdout = [], rc, stdout

    def __call__(self, *cmd, timeout=3):
        self.calls.append(cmd)
        return subprocess.CompletedProcess(cmd, self.rc, self.stdout, "")


class Applying(unittest.TestCase):
    def setUp(self):
        self.orig = A.run
        self.rec = A.run = Recorder()
        self.files = (A.ACCENT_FILE, A.ANIM_FILE, A.SOUND_FILE, A.NIGHTLIGHT_FILE, A.VEIL_FILE)
        for f in self.files:
            A.remove(f)

    def tearDown(self):
        A.run = self.orig
        for f in self.files:
            A.remove(f)

    def test_dry_run_writes_nothing(self):
        ap = A.Applier(dry=True)
        p = A.plan({"part": "late", "focus": True}, values(soundscape="on"))
        lines = ap.apply(p, values())
        self.assertTrue(all(line.startswith("DRY ") for line in lines))
        self.assertTrue(any("soundscape: rain" in line for line in lines))
        for f in self.files:
            self.assertFalse(os.path.exists(f), f)
        self.assertEqual(self.rec.calls, [])
        self.assertIsNone(ap.sound)

    def test_real_run_writes_runtime_files_once(self):
        ap = A.Applier()
        p = A.plan({"part": "day", "focus": True}, values(wallpaper="off"))
        ap.apply(p, values())
        with open(A.SOUND_FILE) as fh:
            self.assertIn("volume=30", fh.read())
        with open(A.NIGHTLIGHT_FILE) as fh:
            self.assertEqual(fh.read().strip(), "400")
        self.assertEqual(A.anim_level(), 1)
        self.assertTrue(any("lua.ambient" in " ".join(c) for c in self.rec.calls))
        n = len(self.rec.calls)
        ap.apply(p, values())
        self.assertEqual(len(self.rec.calls), n)                            # nothing changed: nothing run
        ap.applied.pop("animations")                                        # a reload
        ap.apply(p, values())
        self.assertEqual(len(self.rec.calls), n + 1)
        ap.reset()
        for f in (A.SOUND_FILE, A.NIGHTLIGHT_FILE, A.ACCENT_FILE):
            self.assertFalse(os.path.exists(f), f)
        self.assertEqual(A.anim_level(), 0)

    def test_hold_stops_only_the_soundscape(self):
        ap = A.Applier()
        self.assertEqual(ap.apply({"mood": "day"}, values(), hold=True), [])
        self.assertEqual(self.rec.calls, [])

    def test_lights_on_change_and_retry(self):
        ap = A.Applier()
        sent = []
        ok = [False]

        def fake(scene, v, dry=False, secrets=None):
            sent.append(scene)
            if not ok[0]:
                raise ValueError("bridge offline")
            yield "sent"
        orig, A.lights_apply = A.lights_apply, fake
        try:
            v = values(lights="hue", wallpaper="off", accent="off", nightlight="off", animations="off", notify="off")
            p = A.plan({"part": "day"}, v)
            ap.apply(p, v)
            self.assertEqual(len(sent), 1)
            self.assertTrue(ap.errors)
            ok[0] = True
            ap.apply(p, v)                       # failed before: tried again
            ap.apply(p, v)                       # same mood: left alone (a light changed by hand stays)
            self.assertEqual(len(sent), 2)
            ap.apply(A.plan({"part": "late"}, v), v)
            self.assertEqual(len(sent), 3)
        finally:
            A.lights_apply = orig


class Lights(unittest.TestCase):
    def test_hue_body(self):
        self.assertEqual(A.hue_body({"on": True, "bri": 100, "kelvin": 5000}),
                         {"on": True, "bri": 254, "ct": 200, "transitiontime": 20})
        self.assertEqual(A.hue_body({"on": True, "bri": 1, "kelvin": 1500})["ct"], 500)
        self.assertFalse(A.hue_body({"on": False})["on"])

    def test_ha_calls(self):
        v = values(ha_lights="light.desk,light.lamp")
        self.assertEqual(A.ha_calls({"on": False}, v)[0][0], "/api/services/light/turn_off")
        path, body = A.ha_calls({"on": True, "bri": 60, "kelvin": 2700, "scene": ""}, v)[0]
        self.assertEqual(body["entity_id"], ["light.desk", "light.lamp"])
        self.assertEqual(A.ha_calls({"on": True, "scene": "scene.x"}, v)[0],
                         ("/api/services/scene/turn_on", {"entity_id": "scene.x"}))
        with self.assertRaises(ValueError):
            A.ha_calls({"on": True, "bri": 1, "kelvin": 2700}, values())

    def test_hue_pair_waits_for_the_button(self):
        answers = [[{"error": {"type": 101, "description": "link button not pressed"}}],
                   [{"success": {"username": "abcdef123456"}}]]
        orig = A.hue_request
        A.hue_request = lambda *a, **k: (200, answers.pop(0))
        try:
            self.assertEqual(A.hue_pair("192.168.1.20", sleep=lambda s: None), "abcdef123456")
            answers[:] = [[{"error": {"type": 101}}]] * 5
            t = iter(range(100))
            with self.assertRaises(TimeoutError):
                A.hue_pair("192.168.1.20", wait=2, sleep=lambda s: None, clock=lambda: next(t))
            with self.assertRaises(ValueError):
                A.hue_pair("8.8.8.8")
        finally:
            A.hue_request = orig

    def test_hue_dry_scene(self):
        A.DRY_LOG.clear()
        lines = list(A.lights_apply({"on": True, "bri": 50, "kelvin": 4000}, values(lights="hue",
                                    hue_bridge="192.168.1.20", hue_group="3"), dry=True,
                                    secrets={"hue_user": "abcdef123456"}))
        self.assertTrue(lines[0].startswith("DRY hue 192.168.1.20 group 3"))
        self.assertNotIn("abcdef123456", lines[0])
        self.assertEqual(A.DRY_LOG[0][0], "PUT")

    def test_fake_home_assistant(self):
        seen = []

        class HA(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                seen.append((self.path, self.headers.get("Authorization"), body))
                ok = self.headers.get("Authorization") == "Bearer tok-0123456789abcdefghij"
                self.send_response(200 if ok else 401)
                self.end_headers()
                self.wfile.write(b"[]")

            def log_message(self, *_a):
                pass
        server = http.server.HTTPServer(("127.0.0.1", 0), HA)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            v = values(lights="ha", ha_url=f"http://127.0.0.1:{server.server_port}", ha_lights="light.desk")
            lines = list(A.lights_apply({"on": True, "bri": 60, "kelvin": 2700, "scene": ""}, v,
                                        secrets={"ha_token": "tok-0123456789abcdefghij"}))
            self.assertEqual(seen[0][0], "/api/services/light/turn_on")
            self.assertEqual(seen[0][2]["brightness_pct"], 60)
            self.assertNotIn("tok-0123456789abcdefghij", lines[0])
            with self.assertRaises(ValueError):
                list(A.lights_apply({"on": False}, v, secrets={"ha_token": "wrong-token-0123456789"}))
        finally:
            server.shutdown()
            server.server_close()


class NightLightNudge(unittest.TestCase):
    def test_nudge_only_the_schedule(self):
        import calendar
        state = tempfile.mkdtemp(dir=helpers.SCRATCH)
        env = dict(os.environ, NL_STATE_DIR=state, NL_DRY="1", TZ="UTC",
                   NL_NOW=str(calendar.timegm((2026, 10, 20, 22, 0, 0))),
                   NL_CONF=os.path.join(state, "nightlight.conf"))
        script = os.path.join(helpers.SCRIPTS, "nightlight.sh")

        def status():
            return json.loads(subprocess.run([script, "status", "--json"], env=env, capture_output=True,
                                             text=True).stdout)["now_temp"]
        self.assertEqual(status(), 4000)
        with open(os.path.join(state, "ambient"), "w") as fh:
            fh.write("-400\n")
        self.assertEqual(status(), 3600)
        with open(os.path.join(state, "ambient"), "w") as fh:
            fh.write("warm; rm -rf ~\n")
        self.assertEqual(status(), 4000)                    # not a sane number: ignored
        with open(os.path.join(state, "ambient"), "w") as fh:
            fh.write("-3500\n")
        self.assertEqual(status(), 1000)                    # clamped
        subprocess.run([script, "on", "3000"], env=env, capture_output=True)
        self.assertEqual(status(), 3000)                    # an override is never nudged


@unittest.skipUnless(shutil.which("ffmpeg"), "no ffmpeg")
class Soundscape(unittest.TestCase):
    def test_render_short_loops(self):
        folder = tempfile.mkdtemp(dir=helpers.SCRATCH)
        for kind in A.SOUND_KINDS:
            out = os.path.join(folder, f"{kind}.ogg")
            self.assertTrue(A.make_sound(kind, out=out, seconds=6), kind)
            self.assertGreater(os.path.getsize(out), 1000)

    def test_mpv_argv(self):
        argv = A.mpv_argv("/x/rain.ogg", 20)
        self.assertIn("--no-video", argv)
        self.assertIn("--no-config", argv)
        self.assertIn("--volume=20", argv)
        self.assertEqual(argv[-2:], ["--", "/x/rain.ogg"])


class PageWording(unittest.TestCase):
    def setUp(self):
        import importlib
        self.page = importlib.import_module("settings_pages.ambient")

    def test_status(self):
        data = {"settings": values(), "plan": {"mood": "night", "why": "the night light's hours"}}
        self.assertTrue(self.page.status_text(data).startswith("Off."))
        data["settings"] = values(enabled="on")
        data["service"] = "active"
        self.assertEqual(self.page.status_text(data), "Night: the night light's hours")
        data["inputs"] = {"gamemode": True}
        self.assertIn("gamemode", self.page.status_text(data))

    def test_lights_text(self):
        self.assertIn("never touched", self.page.lights_text({"settings": values()}))
        self.assertIn("not paired", self.page.lights_text({"settings": values(lights="hue",
                                                                               hue_bridge="192.168.1.2")}))
        self.assertIn("a token", self.page.lights_text({"settings": values(lights="ha", ha_url="http://x")}))


if __name__ == "__main__":
    unittest.main()


class ReviewFixes(unittest.TestCase):
    """What the adversarial review found: a redirect carrying the token, a
    stale pid file, an orphaned `soundscape now`, a real `tick` outside the
    daemon, `set enabled` skipping the service, a strength change not
    re-tinting the accent."""

    def test_redirect_is_not_followed(self):
        hits = []

        class Target(http.server.BaseHTTPRequestHandler):
            def do_GET(self):           # urllib turns a POST's 302 into a GET, headers and all
                hits.append(self.headers.get("Authorization"))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"[]")

            def log_message(self, *_a):
                pass
        target = http.server.HTTPServer(("127.0.0.1", 0), Target)

        class Redirect(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{target.server_port}/stolen")
                self.end_headers()

            def log_message(self, *_a):
                pass
        server = http.server.HTTPServer(("127.0.0.1", 0), Redirect)
        for s in (target, server):
            threading.Thread(target=s.serve_forever, daemon=True).start()
        try:
            status, _ = A.http("POST", f"http://127.0.0.1:{server.server_port}/api/services/light/turn_on",
                               {"entity_id": "light.desk"}, headers={"Authorization": "Bearer secret-token-xyz"})
            self.assertEqual(status, 302)
            self.assertEqual(hits, [])          # the token went nowhere else
        finally:
            for s in (target, server):
                s.shutdown()
                s.server_close()

    def test_stale_pid_is_not_signalled(self):
        A.write_file(A.PIDFILE, f"{os.getpid()}\n")       # a live process that is not the daemon
        try:
            self.assertIsNone(A.daemon_pid())
            self.assertFalse(A.poke())
        finally:
            A.remove(A.PIDFILE)

    def test_soundscape_now_without_the_service_leaves_nothing(self):
        A.remove(A.PIDFILE)
        with self.assertRaises(SystemExit):
            A.soundscape_cmd("now")
        self.assertFalse(os.path.exists(A.NOW_FILE))

    def test_real_tick_needs_the_daemon(self):
        A.remove(A.PIDFILE)
        os.environ.pop("AMBIENT_DRY", None)
        with self.assertRaises(SystemExit) as cm:
            A.main(["tick"])
        self.assertIn("not running", str(cm.exception.code))

    def test_set_enabled_goes_through_the_master_switch(self):
        seen = []
        orig = A.set_master
        A.set_master = lambda state, dry=False: seen.append(state)
        try:
            A.main(["set", "enabled", "on"])
            with self.assertRaises(SystemExit):
                A.main(["set", "enabled", "maybe"])
        finally:
            A.set_master = orig
        self.assertEqual(seen, ["on"])

    def test_strength_change_tints_again(self):
        orig, A.run = A.run, Recorder()
        try:
            ap = A.Applier()
            v = values(wallpaper="off", nightlight="off", animations="off", notify="off")
            p = A.plan({"part": "late"}, v)
            ap.apply(p, v)
            n = len(A.run.calls)
            ap.apply(p, v)
            self.assertEqual(len(A.run.calls), n)
            v2 = values(wallpaper="off", nightlight="off", animations="off", notify="off", strength="medium")
            ap.apply(A.plan({"part": "late"}, v2), v2)
            self.assertTrue(any("theme-from-wallpaper.py" in " ".join(c) for c in A.run.calls[n:]))
        finally:
            A.run = orig
            A.remove(A.ACCENT_FILE)
