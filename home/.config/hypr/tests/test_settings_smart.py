"""Settings > Smart desktop (settings_pages/_smart.py): reading each smart
feature's state from its CLI's JSON, the commands its switch runs, the keys
found by description, and the "privacy at a glance" strip. Every probe is
fed by hand and every subprocess call is stubbed: nothing is switched."""
import os
import subprocess
import unittest
from unittest import mock

import helpers  # noqa: F401  (scratch XDG dirs, scripts/ on the path)

from settings_pages import _catalog
from settings_pages import _smart as S


def done(stdout="", rc=0, stderr=""):
    return subprocess.CompletedProcess([], rc, stdout=stdout, stderr=stderr)


def conf(**over):
    c = dict(S.privacy_settings.DEFAULTS)
    c.update(over)
    return c


class Reading(unittest.TestCase):
    def test_parse_units(self):
        text = ("Id=automations.service\nActiveState=active\nUnitFileState=enabled\n\n"
                "Id=phone-handoff.service\nActiveState=inactive\nUnitFileState=disabled\n")
        self.assertEqual(S.parse_units(text), {
            "automations.service": {"active": "active", "enabled": "enabled"},
            "phone-handoff.service": {"active": "inactive", "enabled": "disabled"}})

    def test_run_json_null_and_junk(self):
        with mock.patch.object(S.subprocess, "run", return_value=done("null\n")):
            self.assertEqual(S.run_json(["x"]), {"none": True})
        with mock.patch.object(S.subprocess, "run", return_value=done("Traceback ...")):
            self.assertIsNone(S.run_json(["x"]))
        with mock.patch.object(S.subprocess, "run", side_effect=subprocess.TimeoutExpired("x", 1)):
            self.assertIsNone(S.run_json(["x"]))

    def test_gather_adds_the_always_probes(self):
        with mock.patch.object(S, "probe", side_effect=lambda n: n.upper()):
            got = S.gather(["tasks"])
        self.assertEqual(set(got), {"tasks", *S.ALWAYS})
        self.assertEqual(got["tasks"], "TASKS")

    def test_probes_of(self):
        self.assertEqual(S.probes_of(["memory", "focus"]), ["focus", "privacy", "units"])

    def test_keys_for(self):
        binds = [{"keys": "SUPER+CTRL+V", "desc": "Tools: Voice typing (start / stop and type)"},
                 {"keys": "SUPER+ALT+V", "desc": "Tools: Voice typing, hold to talk"},
                 {"keys": "SUPER+ALT+V", "desc": "Tools: Voice typing, hold to talk (release)"},
                 {"keys": "SUPER+SHIFT+V", "desc": "Tools: Live captions on / off"},
                 {"keys": "SUPER+X", "desc": "Tools: Voice typing old", "state": "off"},
                 {"keys": "escape", "desc": "Tools: Voice typing", "submap": "resize"}]
        self.assertEqual(S.keys_for(S.BY_ID["voice"], binds), ["SUPER+CTRL+V", "SUPER+ALT+V", "SUPER+SHIFT+V"])
        self.assertEqual(S.keys_for(S.BY_ID["smartclip"], binds), [])

    def test_a_broken_answer_is_an_error_card(self):
        st = S.feature_state(S.BY_ID["tasks"], {"tasks": {"settings": "not a dict"}})
        self.assertEqual(st["kind"], "error")
        self.assertFalse(st["can_toggle"])
        st = S.feature_state(S.BY_ID["suggestions"], {})
        self.assertEqual(st["kind"], "error")


class States(unittest.TestCase):
    def test_assistant(self):
        p = {"assistant": {"settings": {"enabled": "off"}}}
        self.assertEqual(S.st_assistant(p)["on"], False)
        p = {"assistant": {"settings": {"model": "auto"}, "roles": {"default": {"name": "qwen"}}}}
        st = S.st_assistant(p)
        self.assertTrue(st["on"])       # a missing key means on
        self.assertIn("qwen", st["text"])
        self.assertEqual(st["uses"][0][0], "screen")

    def test_voice_captions_and_dictation_use_the_mic(self):
        st = S.st_voice({"voice": {"installed": True, "state": "recording", "captions": True, "settings": {}}})
        self.assertTrue(st["on"])
        self.assertEqual([u[0] for u in st["uses"]], ["mic", "mic"])
        self.assertEqual(st["uses"][0][2], [S.VOICE, "cancel"])
        st = S.st_voice({"voice": {"installed": True, "state": "off", "captions": False, "settings": {}}})
        self.assertEqual((st["on"], st["kind"], st["uses"]), (False, "demand", []))

    def test_voice_commands(self):
        st = S.st_voice_commands({"voice": {"settings": {"commands": "off"}}})
        self.assertFalse(st["on"])
        self.assertFalse(st["extras"][0][3])        # confirm dimmed while off
        st = S.st_voice_commands({"voice": {"settings": {"commands": "on", "command_confirm": "on"}}})
        self.assertTrue(st["extras"][0][2])

    def test_memory(self):
        p = {"privacy": conf(memory="on", memory_screen="on", memory_clipboard="on"), "units": {}}
        st = S.st_memory(p)
        senses = sorted(u[0] for u in st["uses"])
        self.assertEqual(senses, ["clipboard", "clipboard", "screen"])     # ask's clipboard, memory's, screen
        self.assertIn([S.PRIVACY, "memory", "screen", "off"], [u[2] for u in st["uses"]])
        p = {"privacy": conf(memory="off", ask="off"), "units": {}}
        st = S.st_memory(p)
        self.assertEqual((st["on"], st["uses"]), (False, []))
        p = {"privacy": conf(), "units": {"desktop-memory.timer": {"active": "failed"}}}
        self.assertEqual(S.st_memory(p)["kind"], "error")

    def test_presence_needs_its_service(self):
        base = {"installed": {"venv": True, "model": True}}
        self.assertEqual(S.st_presence({"presence": dict(base, on=False)})["uses"], [])
        st = S.st_presence({"presence": dict(base, on=True, service="inactive")})
        self.assertEqual((st["kind"], st["uses"][0][0]), ("error", "camera"))
        st = S.st_presence({"presence": dict(base, on=True, service="active", live={"state": "here"})})
        self.assertEqual(st["kind"], "running")
        st = S.st_presence({"presence": {"installed": {"venv": False}, "on": False}})
        self.assertEqual(st["kind"], "setup")

    def test_gestures_and_gaze(self):
        d = {"switches": {"gestures": False, "gaze": True}, "installed": {"venv": True}, "service": "active"}
        st = S.st_gestures({"gestures": d})
        self.assertFalse(st["on"])
        self.assertEqual(st["kind"], "running")
        self.assertEqual(st["uses"], [("camera", "Gaze (which monitor you look at)", [S.PRIVACY, "gaze", "off"])])

    def test_layout_modes(self):
        for mode, on, place in (("off", False, False), ("learn", True, False), ("on", True, True)):
            st = S.st_layout({"layout": {"settings": {"mode": mode}, "apps": []}, "units": {}})
            self.assertEqual((st["on"], st["extras"][0][2]), (on, place), mode)

    def test_brief_and_digest_follow_their_rules(self):
        rules = {"rules": [{"id": "daily-brief", "enabled": False}, {"id": "end-of-day", "enabled": True},
                           {"id": "dnd-digest", "enabled": True}], "running": False}
        st = S.st_brief({"automations": rules})
        self.assertEqual((st["on"], st["extras"][0][2], st["kind"]), (False, True, "error"))
        self.assertEqual(S.st_digest({"automations": rules})["kind"], "error")
        rules["running"] = True
        self.assertEqual(S.st_digest({"automations": rules})["kind"], "running")
        self.assertEqual(S.st_digest({"automations": {"rules": []}})["kind"], "setup")

    def test_automations_is_its_unit(self):
        d = {"rules": [{"id": "a", "enabled": True}, {"id": "b", "enabled": True, "paused": 5}], "broken": []}
        st = S.st_automations({"automations": d, "units": {"automations.service": {"active": "active",
                                                                                     "enabled": "enabled"}}})
        self.assertEqual((st["on"], st["kind"]), (True, "running"))
        self.assertIn("1 of 2", st["text"])
        st = S.st_automations({"automations": d, "units": {"automations.service": {"active": "inactive",
                                                                                     "enabled": "disabled"}}})
        self.assertFalse(st["on"])

    def test_machines_before_pairing(self):
        st = S.st_machines({"peers": {"enabled": False, "peers": [], "kvm": {}}, "privacy": conf()})
        self.assertEqual((st["kind"], st["can_toggle"]), ("setup", False))
        d = {"enabled": True, "service": "active, enabled", "kvm": {"installed": True, "on": False},
             "peers": [{"name": "laptop", "seen": S.time.time()}]}
        st = S.st_machines({"peers": d, "privacy": conf(machines_clipboard="on")})
        self.assertEqual(st["kind"], "running")
        self.assertIn("laptop online", st["text"])
        self.assertEqual(st["uses"][0][0], "clipboard")

    def test_pip_and_on_demand_cards(self):
        st = S.st_pip({"pip": {"none": True}})
        self.assertEqual((st["on"], st["kind"]), (None, "demand"))
        st = S.st_pip({"pip": {"mode": "window", "title": "Firefox"}})
        self.assertEqual(st["uses"][0], ("screen", "Picture-in-picture: mirroring a window", [S.PIP, "close"]))
        self.assertEqual(S.st_contexts({"contexts": {"contexts": [{"name": "Atlas"}],
                                                     "current": {"name": "Atlas"}}})["text"], "in Atlas now")
        self.assertEqual(S.st_screen_ask({"screenask": {"model": None, "why": "none"}})["kind"], "setup")

    def test_phone_handoff_and_phone_ask(self):
        p = {"phone": {"kdeconnect": True, "phone": "Pixel", "codes": False},
             "units": {"phone-handoff.service": {"active": "active", "enabled": "enabled"}}}
        st = S.st_phone(p)
        self.assertEqual((st["on"], st["kind"]), (True, "running"))
        st = S.st_phone_ask({"phoneask": {"on": True, "screen": True, "listener": False, "devices": [{"name": "x"}]}})
        self.assertEqual((st["kind"], st["uses"][0][2]), ("error", [S.PHONE_ASK, "screen", "off"]))

    def test_health_and_tasks(self):
        d = {"task": {"exists": True, "enabled": True, "last_result": "ok", "schedule": "daily 03:30"},
             "tasks": {"enabled": False}, "report": {"findings": []}}
        self.assertEqual(S.st_health({"health": d})["kind"], "error")    # tasks off: the checkup never runs
        self.assertEqual(S.st_tasks({"tasks": {"settings": {"enabled": True}, "daemon": {}}})["kind"], "error")


class Switches(unittest.TestCase):
    def test_the_real_master_switches(self):
        want = {
            "assistant": [S.ASSISTANT, "set", "enabled", "on"],
            "voice": [S.VOICE, "captions", "on"],
            "voice-commands": [S.VOICE, "set", "commands", "on"],
            "speech": [S.TTS, "set", "enabled", "on"],
            "memory": [S.PRIVACY, "memory", "on"],
            "presence": [S.PRIVACY, "presence", "on"],
            "gestures": [S.PRIVACY, "gestures", "on"],
            "suggestions": [S.SUGGEST, "set", "on"],
            "smartclip": [S.SMARTCLIP, "set", "on"],
            "layout": [S.LAYOUT, "set", "mode", "learn"],
            "focus": [S.FOCUS, "set", "on"],
            "tasks": [S.TASKS, "on"],
            "brief": [S.AUTOMATIONS, "enable", "daily-brief"],
            "sessions": [S.SESSIONS, "set", "autosave", "on"],
            "automations": ["systemctl", "--user", "enable", "--now", "automations.service"],
            "digest": [S.AUTOMATIONS, "enable", "dnd-digest"],
            "ambient": [S.AMBIENT, "set", "on"],
            "health": [S.HEALTH, "set", "enabled", "on"],
            "phone": ["systemctl", "--user", "enable", "--now", "phone-handoff.service"],
            "phone-ask": [S.PHONE_ASK, "on"],
            "machines": [S.PEERS, "set", "enabled", "on"],
        }
        for fid, argv in want.items():
            self.assertEqual(S.switch_commands(fid, True), [argv], fid)
            off = S.switch_commands(fid, False)[0]
            self.assertEqual(len(off), len(argv), fid)
        self.assertEqual(S.switch_commands("layout", False), [[S.LAYOUT, "set", "mode", "off"]])
        self.assertEqual(S.switch_commands("brief", False), [[S.AUTOMATIONS, "disable", "daily-brief"]])
        for fid in ("screen-ask", "contexts", "pip", "ai"):
            self.assertEqual(S.switch_commands(fid, True), [], fid)

    def test_extras(self):
        self.assertEqual(S.extra_commands("layout", "place", False), [[S.LAYOUT, "set", "mode", "learn"]])
        self.assertEqual(S.extra_commands("gestures", "gaze", True), [[S.PRIVACY, "gaze", "on"]])
        self.assertEqual(S.extra_commands("machines", "kvm", False), [[S.PEERS, "kvm", "off"]])
        self.assertEqual(S.extra_commands("phone", "codes", True), [[S.PHONE, "codes", "on"]])

    def test_execute_stops_at_the_first_failure(self):
        calls = []

        def fake(argv, **_kw):
            calls.append(argv)
            return done(rc=1, stderr="nope\nrefused: no machine paired") if argv[0] == "b" else done()
        with mock.patch.object(S.subprocess, "run", side_effect=fake):
            self.assertEqual(S.execute([["a"], ["b"], ["c"]]), "b: refused: no machine paired")
        self.assertEqual(calls, [["a"], ["b"]])

    def test_every_command_is_a_real_script(self):
        for f in S.FEATURES:
            for value in (True, False):
                for argv in S.switch_commands(f["id"], value):
                    if argv[0] != "systemctl":
                        self.assertTrue(os.access(argv[0], os.X_OK), argv[0])
        for name, argv in S.PROBES.items():
            self.assertTrue(os.access(argv[0], os.X_OK), name)


class Privacy(unittest.TestCase):
    def test_strip(self):
        states = {"presence": S.state(True, "running", "", uses=[("camera", "Presence", ["p", "off"])]),
                  "smartclip": S.state(True, "running", "", uses=[("clipboard", "Smart", ["s", "off"])])}
        p = {"units": {"cliphist@text.service": {"active": "active", "enabled": "enabled"}},
             "camera_now": {"class": "active", "tooltip": "Camera\npresence.py"}, "mic_now": {"class": "idle"}}
        view = S.privacy_view(states, p)
        self.assertEqual([i[0] for i in view["clipboard"]["items"]], ["Clipboard history (cliphist)", "Smart"])
        self.assertEqual(view["camera"]["now"], ["presence.py"])
        self.assertIn("in use now: presence.py", S.sense_summary("camera", view["camera"]))
        self.assertEqual(S.sense_summary("mic", view["mic"]), "nothing here may use it on its own")


class PageEntry(unittest.TestCase):
    def test_page_is_listed_first_and_finds_every_feature(self):
        pages = _catalog.read_pages()
        self.assertEqual(pages[0]["id"], "intelligence")
        ids = {p["id"] for p in pages}
        hub = pages[0]
        for f in S.FEATURES:
            self.assertIn(f["page"], ids, f["id"])
            self.assertIn(f["group"], S.GROUP_ORDER, f["id"])
        for words in ("assistant", "asistente", "gestos", "portapapeles", "machines", "focus guard", "ambiente"):
            self.assertIn(hub, _catalog.search(pages, words), words)


if __name__ == "__main__":
    unittest.main()
