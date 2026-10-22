"""scripts/voice-command.py (voice commands): the fast sentences, the model's
answer read and checked against a fixed catalog, every action's checks
(windows, apps, folders, links, durations, names), when it asks first, the
refusals (shell, raw commands, unknown actions, secret folders) -- and the
whole flow run for real against fake commands: hyprctl, notify-send,
playerctl, wpctl, systemd-run and the sibling scripts are stand-ins in a
scratch folder that only write down how they were called. voice.py's
command mode (settings, the hand-off) and the Settings page's plan text too.

Hermetic: no model is asked (a stub answers), no window moved, no
notification shown, nothing recorded; HYPRLAND_INSTANCE_SIGNATURE is unset
by helpers.py, and PATH starts with the fakes for the flow tests."""
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from unittest import mock

import helpers

vc = helpers.import_script("voice-command.py")
voice = helpers.import_script("voice.py")


def client(address, cls, title="", ws="1", floating=False, fullscreen=0):
    return {"address": address, "class": cls, "initialClass": cls, "title": title,
            "workspace": {"id": int(ws) if ws.isdigit() else -98, "name": ws},
            "floating": floating, "fullscreen": fullscreen, "mapped": True}


CLIENTS = [
    client("0xa1", "org.mozilla.firefox", "News — Mozilla Firefox", "1"),
    client("0xb2", "kitty", "~/Projects/Atlas", "2"),
    client("0xc3", "google-chrome", "Mail - Google Chrome", "4"),
    client("0xc4", "google-chrome", "Docs - Google Chrome", "4"),
    client("0xd5", "org.keepassxc.KeePassXC", "Passwords.kdbx - KeePassXC", "3"),
    client("0xe6", "mpv", "Incognito film - mpv", "5"),
]
APPS = [
    {"id": "org.mozilla.firefox.desktop", "label": "Firefox", "names": ["firefox", "web browser"],
     "keywords": ["internet"], "stem": "firefox"},
    {"id": "org.gnome.Calculator.desktop", "label": "Calculator", "names": ["calculator", "calculadora"],
     "keywords": ["math"], "stem": "calculator"},
    {"id": "steam.desktop", "label": "Steam", "names": ["steam"], "keywords": ["games"], "stem": "steam"},
    {"id": "com.valvesoftware.Steam.desktop", "label": "Steam (Flatpak)", "names": ["steam"],
     "keywords": [], "stem": "steam"},
    {"id": "org.gnome.Loupe.desktop", "label": "Image Viewer", "names": ["image viewer", "visor de imagenes"],
     "keywords": ["photo"], "stem": "loupe"},
]


class FakeWorld:
    def __init__(self, clients=CLIENTS, active="0xa1", shown=("1", "2")):
        self._clients = clients
        self._active = next((c for c in clients if c["address"] == active), {})
        self._shown = shown
        self.dnd_on, self.ids = False, {"t1"}

    def clients(self):
        return self._clients

    def active(self):
        return self._active

    def monitors(self):
        return [{"name": f"M{i}", "activeWorkspace": {"name": n}, "specialWorkspace": {"name": ""}}
                for i, n in enumerate(self._shown)]

    def active_workspace(self):
        return {"id": 1, "name": "1"}

    def themes(self):
        return ["cyberpunk", "matrix", "aero", "win95", "moe"]

    def current_theme(self):
        return "matrix"

    def sessions(self):
        return ["Work", "Evening"]

    def contexts(self):
        return ["Atlas", "Ledger"]

    def apps(self):
        return APPS

    def private(self):
        return {"mpv"}

    def dnd(self):
        return self.dnd_on

    def sink(self):
        return "alsa_output.speakers"

    def timer_ids(self):
        return set(self.ids)

    def muted(self):
        return False


def one(act, world=None, lang="en"):
    steps, refused = vc.plan([act], world or FakeWorld(), lang)
    return (steps[0] if steps else None), refused


# -- the fast sentences -------------------------------------------------------------------
class Fast(unittest.TestCase):
    def test_media_and_volume(self):
        cases = {"Pause.": ("media", "pause"), "pausa la música": ("media", "pause"), "¿Pausa?": ("media", "pause"),
                 "Play": ("media", "play"), "reanudar": ("media", "play"), "Next song": ("media", "next"),
                 "Siguiente canción.": ("media", "next"), "la anterior": ("media", "previous"),
                 "stop the music": ("media", "stop"), "Sube el volumen": ("volume", "up"),
                 "volume down please": ("volume", "down"), "Silencio": ("volume", "mute"),
                 "por favor quita el silencio": ("volume", "unmute")}
        for said, (action, value) in cases.items():
            with self.subTest(said=said):
                self.assertEqual(vc.fast_parse(said), [{"action": action, "value": value}])

    def test_windows_and_workspaces(self):
        self.assertEqual(vc.fast_parse("Full screen."), [{"action": "fullscreen"}])
        self.assertEqual(vc.fast_parse("pantalla completa"), [{"action": "fullscreen"}])
        self.assertEqual(vc.fast_parse("Close this window"), [{"action": "close"}])
        self.assertEqual(vc.fast_parse("Cierra la ventana."), [{"action": "close"}])
        self.assertEqual(vc.fast_parse("go to workspace 3"), [{"action": "workspace", "workspace": 3}])
        self.assertEqual(vc.fast_parse("Escritorio dos"), [{"action": "workspace", "workspace": 2}])
        self.assertEqual(vc.fast_parse("ve al escritorio 5"), [{"action": "workspace", "workspace": 5}])

    def test_dnd(self):
        for said in ("Do not disturb", "don't disturb", "activa no molestar", "No molestar."):
            self.assertEqual(vc.fast_parse(said), [{"action": "dnd", "value": "on"}], said)
        for said in ("turn off do not disturb", "desactiva no molestar", "do not disturb off"):
            self.assertEqual(vc.fast_parse(said), [{"action": "dnd", "value": "off"}], said)

    def test_longer_sentences_go_to_the_model(self):
        for said in ("pause the music and go to workspace 2", "close all the windows", "close firefox",
                     "no molestar durante una hora", "move firefox to workspace 3", "play some jazz on spotify"):
            self.assertIsNone(vc.fast_parse(said), said)


# -- the model's answer ---------------------------------------------------------------------
# What a well-behaved model answers for each sentence (EN + ES): the stub
# hands it back, the rest is real (parsing, checking, words).
PHRASES = {
    "move firefox to workspace 3": {"actions": [{"action": "move", "app": "firefox", "workspace": 3}], "sure": True},
    "mueve firefox al escritorio 3": {"actions": [{"action": "move", "app": "Firefox", "workspace": 3}], "sure": True},
    "put the terminal and firefox side by side":
        {"actions": [{"action": "side-by-side", "app": "terminal", "app2": "firefox"}], "sure": True},
    "pon la terminal y el navegador lado a lado":
        {"actions": [{"action": "side-by-side", "app": "terminal", "app2": "browser"}], "sure": True},
    "do not disturb for an hour": {"actions": [{"action": "dnd-for", "minutes": 60}], "sure": True},
    "no molestar durante media hora": {"actions": [{"action": "dnd-for", "minutes": 30}], "sure": True},
    "set a timer for 10 minutes for the tea": {"actions": [{"action": "timer", "minutes": 10, "text": "tea"}],
                                               "sure": True},
    "pon un temporizador de 90 segundos": {"actions": [{"action": "timer", "minutes": 1.5}], "sure": True},
    "remind me in 20 minutes to call the lab":
        {"actions": [{"action": "reminder", "minutes": 20, "text": "call the lab"}], "sure": True},
    "recuérdame a las 5 de la tarde llamar a mamá":
        {"actions": [{"action": "reminder", "time": "17:00", "text": "llamar a mamá"}], "sure": True},
    "wake me up at 7:30": {"actions": [{"action": "alarm", "time": "7:30"}], "sure": True},
    "switch to the aero theme": {"actions": [{"action": "theme", "value": "Aero"}], "sure": True},
    "cambia al tema matrix y ve al escritorio 2":
        {"actions": [{"action": "theme", "value": "matrix"}, {"action": "workspace", "workspace": 2}], "sure": True},
    "open my downloads and pause the music":
        {"actions": [{"action": "open-folder", "text": "downloads"}, {"action": "media", "value": "pause"}],
         "sure": True},
    "abre mis descargas": {"actions": [{"action": "open-folder", "text": "descargas"}], "sure": True},
    "open the calculator": {"actions": [{"action": "launch", "app": "calculator"}], "sure": True},
    "abre la calculadora": {"actions": [{"action": "launch", "app": "calculadora"}], "sure": True},
    "abre el navegador": {"actions": [{"action": "launch", "app": "navegador"}], "sure": True},
    "open github dot com": {"actions": [{"action": "open-url", "text": "github dot com"}], "sure": True},
    "restore my work session": {"actions": [{"action": "session", "value": "work"}], "sure": True},
    "guarda esta sesión como tarde": {"actions": [{"action": "session-save", "value": "Tarde"}], "sure": True},
    "work on atlas": {"actions": [{"action": "context", "value": "atlas"}], "sure": True},
    "sal del proyecto": {"actions": [{"action": "context", "value": "salir"}], "sure": True},
    "search my desktop for the invoice from march":
        {"actions": [{"action": "search", "text": "invoice from march"}], "sure": True},
    "busca el pdf de facturas": {"actions": [{"action": "search", "text": "pdf de facturas"}], "sure": True},
    "make firefox fullscreen": {"actions": [{"action": "fullscreen", "app": "firefox"}], "sure": True},
    "turn on the night light": {"actions": [{"action": "nightlight", "value": "on"}], "sure": True},
    "apaga el modo juego": {"actions": [{"action": "gamemode", "value": "apagar"}], "sure": True},
    "show me what I missed": {"actions": [{"action": "digest"}], "sure": True},
    "salta a la siguiente canción y sube el volumen":
        {"actions": [{"action": "media", "value": "next"}, {"action": "volume", "value": "up"}], "sure": True},
}


class Model(unittest.TestCase):
    def understood(self, said, answer, lang="en"):
        got = vc.understand(said, FakeWorld(), ask=lambda prompt: json.dumps(answer))
        return vc.plan(got["actions"], FakeWorld(), lang, got["sure"]) + (got,)

    def test_every_phrase_plans_cleanly(self):
        # A home of its own with the usual folders, so the phrases that open
        # one pass on any machine (a fresh account may not have ~/Downloads).
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root)
        for d in ("Downloads", "Music", "Documents", "Pictures", "Videos", "Desktop"):
            os.makedirs(os.path.join(root, d))
        home = mock.patch.object(vc, "HOME", root)
        dirs = mock.patch.object(vc, "user_dir", return_value=None)
        home.start(); dirs.start()
        self.addCleanup(home.stop); self.addCleanup(dirs.stop)
        for said, answer in PHRASES.items():
            with self.subTest(said=said):
                lang = vc.guess_language(said)
                steps, refused, got = self.understood(said, answer, lang)
                self.assertEqual(refused, [], said)
                self.assertEqual([s["action"] for s in steps], [a["action"] for a in answer["actions"]])
                for s in steps:
                    self.assertTrue(s["say"] and s["ops"], s)

    def test_language_guess(self):
        self.assertEqual(vc.guess_language("pon la terminal y el navegador lado a lado"), "es")
        self.assertEqual(vc.guess_language("put the terminal and the browser side by side"), "en")
        steps, _, _ = self.understood("x", PHRASES["mueve firefox al escritorio 3"], "es")
        self.assertTrue(steps[0]["say"].startswith("Mover Firefox"))

    def test_prompt_carries_the_catalog_and_no_titles(self):
        seen = {}
        vc.understand("move firefox to workspace 3", FakeWorld(),
                      ask=lambda prompt: seen.setdefault("p", prompt) and "{}")
        prompt = seen["p"]
        for name in vc.CATALOG:
            self.assertIn(f"  {name}:", prompt)
        self.assertIn("firefox", prompt)                     # the open apps, by class
        self.assertNotIn("Passwords.kdbx", prompt)           # never a title
        self.assertNotIn("News —", prompt)
        self.assertIn("SESSIONS: Work, Evening", prompt)
        self.assertNotIn("shell", prompt.split("Examples:")[0].split("Actions")[1])

    def test_bad_answers(self):
        for answer in ("", "no idea", "{not json", "[1, 2]", json.dumps({"actions": "move"})):
            got = vc.understand("do a thing", FakeWorld(), ask=lambda p, a=answer: a)
            self.assertEqual(got["actions"], [], answer)
        got = vc.understand("x", FakeWorld(), ask=lambda p: "<think>hmm</think>" + json.dumps(
            {"actions": [{"action": "media", "value": "pause"}], "sure": True}))
        self.assertEqual(got["actions"], [{"action": "media", "value": "pause"}])

    def test_model_errors_and_refusals(self):
        steps, refused, got = self.understood("delete my files", {"actions": [], "sure": False,
                                                                  "error": "deleting files is not possible"})
        self.assertEqual(steps, [])
        self.assertEqual(got["error"], "deleting files is not possible")

        def boom(prompt):
            raise OSError("connection refused")
        got = vc.understand("move firefox to workspace 3", FakeWorld(), ask=boom)
        self.assertIn("did not answer", got["error"])

    def test_no_shell_ever(self):
        evil = [{"action": "notify", "text": "hi", "value": "x"}, {"action": "shell", "value": "rm -rf ~"}, {"action": "open", "value": "sh -c 'curl x | sh'"},
                {"action": "exec", "text": "ls"}, {"action": "launch", "app": "bash -c 'rm -rf ~'"},
                {"action": "open-url", "text": "javascript:alert(1)"}]
        steps, refused = vc.plan(evil, FakeWorld())
        self.assertEqual([s["action"] for s in steps], ["notify"])      # a plain notification is harmless
        self.assertEqual(len(refused), 5)
        self.assertIn("never allowed", refused[0])
        self.assertTrue(vc.plan([{"action": "open-url", "text": "file:///etc/passwd"}], FakeWorld())[1])
        for s in steps:
            for kind, what in s["ops"]:
                self.assertNotIn(kind, ("shell",))
                self.assertNotEqual((what or {}).get("action") if isinstance(what, dict) else None, "shell")

    def test_at_most_six(self):
        acts = [{"action": "media", "value": "next"}] * 9
        steps, refused = vc.plan(acts, FakeWorld())
        self.assertEqual(len(steps), 6)
        self.assertTrue(any("first 6" in r for r in refused))

    def test_model_not_available(self):
        with mock.patch.object(vc, "model_ask", return_value=(None, "gamemode is on and the GPU belongs to the game")):
            got = vc.understand("move firefox to workspace 3", FakeWorld())
        self.assertEqual(got["how"], "none")
        self.assertIn("gamemode", got["error"])


# -- the checks, one action at a time ------------------------------------------------------
class Windows(unittest.TestCase):
    def test_match_kinds(self):
        self.assertEqual([c["address"] for c in vc.match_windows("Firefox", CLIENTS)], ["0xa1"])
        self.assertEqual([c["address"] for c in vc.match_windows("the browser", CLIENTS)], ["0xa1", "0xc3", "0xc4"])
        self.assertEqual([c["address"] for c in vc.match_windows("chrome", CLIENTS)], ["0xc3", "0xc4"])
        self.assertEqual([c["address"] for c in vc.match_windows("terminal", CLIENTS)], ["0xb2"])
        self.assertEqual([c["address"] for c in vc.match_windows("atlas", CLIENTS)], ["0xb2"])   # title
        self.assertEqual(vc.match_windows("film", CLIENTS, private={"mpv"}), [])        # private title: never
        self.assertEqual(vc.match_windows("passwords", CLIENTS), [])                    # keepass title: never
        self.assertEqual(vc.match_windows("", CLIENTS), [])

    def test_labels_hide_private_titles(self):
        self.assertEqual(vc.window_label(CLIENTS[4]), "KeePassXC")
        self.assertEqual(vc.window_label(CLIENTS[5], {"mpv"}), "Mpv")
        self.assertIn("News", vc.window_label(CLIENTS[0]))

    def test_move_one_and_many(self):
        step, refused = one({"action": "move", "app": "firefox", "workspace": 3})
        self.assertEqual((refused, step["confirm"], step["undo"]), ([], "", "move"))
        self.assertEqual(step["ops"], [("lua", 'hl.dispatch(hl.dsp.window.move({ workspace = "3", follow = false, '
                                               'window = "address:0xa1" }))')])
        step, _ = one({"action": "move", "app": "chrome", "workspace": 6})
        self.assertIn("2 windows", step["confirm"])
        self.assertEqual(len(step["ops"]), 2)
        for bad in (0, 11, "three", None):
            self.assertEqual(one({"action": "move", "app": "firefox", "workspace": bad})[0], None, bad)
        self.assertIn("no open window", one({"action": "move", "app": "gimp", "workspace": 2})[1][0])

    def test_close(self):
        step, _ = one({"action": "close"})                                   # the focused one, on screen
        self.assertEqual(step["confirm"], "")
        self.assertEqual(step["ops"], [("lua", 'hl.dispatch(hl.dsp.window.close({ window = "address:0xa1" }))')])
        step, _ = one({"action": "close", "app": "firefox"})                 # named, and it is the focused one
        self.assertEqual(step["confirm"], "")
        step, _ = one({"action": "close", "app": "terminal"})                # not the focused one: asks
        self.assertIn("does not have the focus", step["confirm"])
        step, _ = one({"action": "close", "app": "chrome"})                  # several: asks
        self.assertIn("closes 2 windows", step["confirm"])
        hidden = FakeWorld(active="0xc3", shown=("1", "2"))                  # focus left on a hidden workspace
        step, refused = one({"action": "close"}, hidden)
        self.assertIsNone(step)
        self.assertIn("cannot see", refused[0])
        nothing = FakeWorld(active="none")
        self.assertIn("no window has the focus", one({"action": "close"}, nothing)[1][0])

    def test_side_by_side(self):
        step, refused = one({"action": "side-by-side", "app": "terminal", "app2": "firefox"})
        self.assertEqual(refused, [])
        lua = "\n".join(op for _, op in step["ops"])
        self.assertIn('hl.dsp.window.move({ workspace = "2", follow = false, window = "address:0xa1" })', lua)
        self.assertIn('hl.dsp.focus({ window = "address:0xb2" })', lua)
        self.assertEqual([w["workspace"] for w in step["windows"]], ["2", "1"])
        step, _ = one({"action": "side-by-side", "app": "firefox", "app2": "chrome"})
        self.assertIn("matches 2 windows", step["confirm"])
        self.assertIn("no other open window", one({"action": "side-by-side", "app": "firefox", "app2": "firefox"})[1][0])

    def test_fullscreen_and_workspace(self):
        step, _ = one({"action": "fullscreen"})
        self.assertIn('hl.dsp.window.fullscreen({ window = "address:0xa1" })', step["ops"][1][1])
        step, _ = one({"action": "workspace", "workspace": 4})
        self.assertEqual(step["ops"], [("lua", vc.summon_lua(4))])
        self.assertIn("hl.dsp.workspace.move({ workspace = id, monitor = mon.name })", vc.summon_lua(4))
        self.assertEqual(step["from"], 1)

    def test_address_is_sanitised(self):
        self.assertEqual(vc.lua_target("0x55d1a2b3"), '"address:0x55d1a2b3"')
        self.assertEqual(vc.lua_target('0xa1" }) os.execute("x'), '"address:none"')


class Checks(unittest.TestCase):
    def test_automation_values(self):
        step, _ = one({"action": "theme", "value": "AERO"})
        self.assertEqual(step["ops"], [("auto", {"action": "theme", "value": "aero"})])
        self.assertIn("no theme", one({"action": "theme", "value": "solarized"})[1][0])
        step, _ = one({"action": "dnd", "value": "activar"})
        self.assertEqual(step["ops"], [("auto", {"action": "dnd", "value": "on"})])
        self.assertTrue(one({"action": "dnd", "value": "maybe"})[1])
        self.assertEqual(one({"action": "session", "value": "evening"})[0]["ops"],
                         [("auto", {"action": "session", "value": "Evening"})])
        self.assertIn("no saved session", one({"action": "session", "value": "gaming"})[1][0])
        self.assertEqual(one({"action": "context", "value": "leave"})[0]["ops"],
                         [("auto", {"action": "context", "value": "leave"})])
        self.assertIn("project context", one({"action": "context", "value": "Kanban"})[1][0])
        step, _ = one({"action": "sound-profile", "value": "card0 output:hdmi"})
        self.assertTrue(step["confirm"])
        step, _ = one({"action": "digest", "value": "x"})
        self.assertEqual(step["ops"], [("auto", {"action": "digest"})])

    def test_session_save_asks_before_replacing(self):
        step, _ = one({"action": "session-save", "value": "New one"})
        self.assertEqual(step["confirm"], "")
        step, _ = one({"action": "session-save", "value": "work"})
        self.assertIn("replaces", step["confirm"])
        self.assertEqual(step["ops"][0][1][-2:], ["save", "Work"])
        self.assertTrue(one({"action": "session-save", "value": "a/../b"})[1])

    def test_launch(self):
        step, _ = one({"action": "launch", "app": "Calculator"})
        self.assertEqual(step["ops"], [("auto", {"action": "open", "value": "org.gnome.Calculator.desktop"})])
        step, _ = one({"action": "launch", "app": "terminal"})
        self.assertEqual(step["ops"][0][0], "detach")
        self.assertEqual(step["ops"][0][1][-2:], ["run", "terminal"])
        step, _ = one({"action": "launch", "app": "steam"})                       # two Steams: asks
        self.assertIn("could also be", step["confirm"])
        self.assertIn("no installed app", one({"action": "launch", "app": "photoshop"})[1][0])

    def test_folders(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root)
        for d in ("Downloads", "Projects/Atlas", "Projects/Ledger", "Projects/Ledger-Notes", ".ssh"):
            os.makedirs(os.path.join(root, d))
        with mock.patch.object(vc, "HOME", root), mock.patch.object(vc, "user_dir", return_value=None):
            self.assertEqual(vc.resolve_folder("my downloads"), os.path.join(root, "Downloads"))
            self.assertEqual(vc.resolve_folder("la carpeta de descargas"), os.path.join(root, "Downloads"))
            github = os.path.join(root, "Projects")
            self.assertEqual(vc.resolve_folder("atlas", github), os.path.join(github, "Atlas"))
            self.assertEqual(vc.resolve_folder("ledger", github), os.path.join(github, "Ledger"))
            self.assertRaises(vc.Refused, vc.resolve_folder, "music", github)          # not there
            self.assertRaises(vc.Refused, vc.resolve_folder, os.path.join(root, ".ssh"), github)
            self.assertRaises(vc.Refused, vc.resolve_folder, "~/.ssh", github)
        self.assertTrue(vc.looks_secret(os.path.expanduser("~/.gnupg/private-keys-v1.d")))

    def test_urls(self):
        self.assertEqual(vc.check_url("github dot com"), "https://github.com")
        self.assertEqual(vc.check_url("https://example.org/a?b=1"), "https://example.org/a?b=1")
        self.assertEqual(vc.check_url("example.org"), "https://example.org")
        for bad in ("javascript:alert(1)", "file:///etc/passwd", "ssh://host", "not a url", "rm -rf /"):
            self.assertRaises(vc.Refused, vc.check_url, bad)

    def test_timers(self):
        step, _ = one({"action": "timer", "minutes": 10, "text": "tea then ! rm -rf ~"})
        argv = step["ops"][0][1]
        self.assertEqual(argv[2:4], ["timer", "0:10:00"])
        self.assertNotIn("then", argv)
        self.assertFalse(any("!" in a or "~" in a for a in argv[4:]), argv)
        step, _ = one({"action": "timer", "minutes": 1.5})
        self.assertEqual(step["ops"][0][1][3], "0:01:30")
        self.assertTrue(one({"action": "timer", "minutes": 100000})[1])
        self.assertTrue(one({"action": "timer", "minutes": -5})[1])
        step, _ = one({"action": "reminder", "time": "17.05", "text": "llamar a mamá"}, lang="es")
        self.assertEqual(step["ops"][0][1][2:5], ["remind", "at", "17:05"])
        self.assertIn("a las 17:05", step["say"])
        self.assertIn("needs when", one({"action": "reminder", "text": "x"})[1][0])
        self.assertTrue(one({"action": "alarm", "time": "25:00"})[1])
        step, _ = one({"action": "dnd-for", "minutes": 60})
        self.assertIn("--on-active=3600s", step["ops"][2][1])
        self.assertEqual(step["say"], "Do Not Disturb for 1 h")

    def test_confirm_rules(self):
        steps, _ = vc.plan([{"action": "media", "value": "pause"}], FakeWorld(), confirm_all=True)
        self.assertEqual(steps[0]["confirm"], "confirm everything is on")
        steps, _ = vc.plan([{"action": "media", "value": "pause"}], FakeWorld(), sure=False)
        self.assertIn("not sure", steps[0]["confirm"])
        steps, refused = vc.plan([{"action": "media", "value": "pause"}, {"action": "teleport"}], FakeWorld())
        self.assertIn("part of what you said", steps[0]["confirm"])
        self.assertEqual(len(refused), 1)
        steps, _ = vc.plan([{"action": "media", "value": "pause"}], FakeWorld())
        self.assertEqual(steps[0]["confirm"], "")

    def test_media_and_volume_values(self):
        self.assertEqual(one({"action": "media", "value": "Play Pause"})[0]["ops"], [("argv", ["playerctl", "play-pause"])])
        self.assertEqual(one({"action": "media", "value": "skip"})[0]["ops"], [("argv", ["playerctl", "next"])])
        self.assertTrue(one({"action": "media", "value": "shuffle; reboot"})[1])
        self.assertEqual(one({"action": "volume", "value": "mute"})[0]["undo"], "volume")
        self.assertTrue(one({"action": "volume", "value": "100"})[1])


# -- the whole flow, against fakes ----------------------------------------------------------
FAKE_TOOL = r'''#!{py}
import json, os, sys
d = os.environ["VC_FAKE"]
name = os.path.basename(sys.argv[0])
with open(os.path.join(d, "calls.log"), "a") as h:
    h.write(json.dumps([name] + sys.argv[1:]) + "\n")
if name == "hyprctl":
    what = sys.argv[1]
    if what == "eval":
        print("ok")
    elif what in ("clients", "activewindow", "monitors", "activeworkspace"):
        print(open(os.path.join(d, what + ".json")).read())
elif name == "notify-send":
    print("7")
    if "--wait" in sys.argv:
        answers = open(os.path.join(d, "answers")).read().split()
        if answers:
            print(answers[0])
            open(os.path.join(d, "answers"), "w").write(" ".join(answers[1:]))
elif name == "makoctl":
    print("default")
elif name == "wpctl" and sys.argv[1] == "get-volume":
    print("Volume: 0.40")
elif name == "pactl":
    print("alsa_output.speakers")
'''
FAKE_SCRIPT = r'''import json, os, sys
d = os.environ["VC_FAKE"]
with open(os.path.join(d, "calls.log"), "a") as h:
    h.write(json.dumps([os.path.basename(sys.argv[0])] + sys.argv[1:]) + "\n")
name = os.path.basename(sys.argv[0])
ids = os.path.join(d, "timer-ids")
if name == "timers.py":
    have = open(ids).read().split() if os.path.exists(ids) else []
    if sys.argv[1:3] == ["list", "--json"]:
        print(json.dumps([{"id": i} for i in have]))
    elif sys.argv[1] in ("timer", "remind", "alarm"):
        open(ids, "w").write(" ".join(have + ["n%d" % len(have)]))
elif name == "theme.py" and sys.argv[1:] == ["current"]:
    print("matrix")
'''


class Flow(unittest.TestCase):
    """handle() for real: plan, notifications, Confirm / Cancel, execute,
    Undo -- every outside command a fake that writes down its argv."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        bin_dir, scripts = os.path.join(self.dir, "bin"), os.path.join(self.dir, "scripts")
        os.makedirs(bin_dir)
        os.makedirs(scripts)
        for tool in ("hyprctl", "notify-send", "playerctl", "wpctl", "systemd-run", "systemctl", "makoctl",
                     "pactl", "uwsm"):
            path = os.path.join(bin_dir, tool)
            with open(path, "w") as h:
                h.write(FAKE_TOOL.replace("{py}", sys.executable))
            os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
        for script in ("timers.py", "theme.py", "notify-settings.py", "sessions.py", "contexts.py",
                       "closed-windows.py", "default-apps.py", "ask-desktop.py", "sound-settings.py", "nightlight.sh"):
            with open(os.path.join(scripts, script), "w") as h:
                h.write(FAKE_SCRIPT)
        self.write("clients", CLIENTS)
        self.write("activewindow", CLIENTS[0])
        self.write("monitors", [{"name": "DP-1", "activeWorkspace": {"id": 1, "name": "1"},
                                 "specialWorkspace": {"id": 0, "name": ""}}])
        self.write("activeworkspace", {"id": 1, "name": "1"})
        self.answers("")
        env = {"VC_FAKE": self.dir, "PATH": bin_dir + os.pathsep + os.environ.get("PATH", "")}
        auto = vc.automations()
        for patch in (mock.patch.dict(os.environ, env), mock.patch.object(vc, "HERE", scripts),
                      mock.patch.object(auto, "HERE", scripts), mock.patch.object(vc, "UNDO_S", 1),
                      mock.patch.object(vc.time, "sleep", lambda s: None), mock.patch.object(vc, "log", lambda t: None)):
            patch.start()
            self.addCleanup(patch.stop)

    def write(self, what, data):
        with open(os.path.join(self.dir, what + ".json"), "w") as h:
            json.dump(data, h)

    def answers(self, *keys):
        with open(os.path.join(self.dir, "answers"), "w") as h:
            h.write(" ".join(keys))

    def calls(self):
        try:
            with open(os.path.join(self.dir, "calls.log")) as h:
                return [json.loads(line) for line in h]
        except OSError:
            return []

    def run_words(self, words, answer=None, conf=None, lang="en"):
        class W(vc.World):
            def themes(self):
                return ["matrix", "aero"]

            def sessions(self):
                return ["Work"]

            def contexts(self):
                return ["Atlas"]

            def apps(self):
                return APPS

            def private(self):
                return set()
        ask = (lambda prompt: json.dumps(answer)) if answer is not None else None
        return vc.handle(words, lang, world=W(), notifier=vc.Notifier(), ask=ask,
                         conf=conf or {"commands": "on", "confirm": False, "language": "auto"})

    def evals(self):
        return [c[2] for c in self.calls() if c[:2] == ["hyprctl", "eval"]]

    def test_move_runs_at_once_and_undo_moves_back(self):
        self.answers("undo")
        result = self.run_words("move firefox to workspace 3",
                                {"actions": [{"action": "move", "app": "firefox", "workspace": 3}], "sure": True})
        self.assertEqual(result["result"], "undone")
        self.assertEqual(self.evals(), [
            'hl.dispatch(hl.dsp.window.move({ workspace = "3", follow = false, window = "address:0xa1" }))',
            'hl.dispatch(hl.dsp.window.move({ workspace = "1", follow = false, window = "address:0xa1" }))'])
        notes = [c for c in self.calls() if c[0] == "notify-send"]
        self.assertTrue(any("undo=Undo" in c for c in notes))
        self.assertTrue(all("-r" in c for c in notes[1:]))                # one bubble, replaced

    def test_no_undo_click_keeps_it(self):
        result = self.run_words("pausa", lang="es")                       # the fast path: no model
        self.assertEqual((result["result"], result["how"]), ("done", "fast"))
        self.assertIn(["playerctl", "pause"], self.calls())

    def test_close_of_another_window_waits_for_confirm(self):
        answer = {"actions": [{"action": "close", "app": "terminal"}], "sure": True}
        self.answers("cancel")
        self.assertEqual(self.run_words("close the terminal", answer)["result"], "cancelled")
        self.assertEqual(self.evals(), [])
        confirm = [c for c in self.calls() if c[0] == "notify-send" and "confirm=Confirm" in c]
        self.assertTrue(confirm and "critical" in confirm[0])
        self.answers("confirm")
        self.assertEqual(self.run_words("close the terminal", answer)["result"], "done")
        self.assertEqual(self.evals(), ['hl.dispatch(hl.dsp.window.close({ window = "address:0xb2" }))'])

    def test_no_answer_is_cancel(self):
        self.answers("")
        conf = {"commands": "on", "confirm": True, "language": "auto"}
        self.assertEqual(self.run_words("pause", conf=conf)["result"], "cancelled")
        self.assertNotIn(["playerctl", "pause"], self.calls())

    def test_automation_actions_go_through_automations(self):
        self.answers("undo")
        result = self.run_words("switch to the aero theme",
                                {"actions": [{"action": "theme", "value": "aero"}], "sure": True})
        self.assertEqual(result["result"], "undone")
        themes = [c for c in self.calls() if c[0] == "theme.py"]
        self.assertEqual(themes, [["theme.py", "current"], ["theme.py", "set", "aero"], ["theme.py", "set", "matrix"]])

    def test_dnd_for_an_hour(self):
        result = self.run_words("no molestar durante una hora",
                                {"actions": [{"action": "dnd-for", "minutes": 60}], "sure": True}, lang="es")
        self.assertEqual(result["result"], "done")
        calls = self.calls()
        self.assertIn(["notify-settings.py", "dnd", "on"], calls)
        timer = next(c for c in calls if c[0] == "systemd-run")
        self.assertIn("--on-active=3600s", timer)
        self.assertEqual(timer[-3:], [os.path.join(vc.HERE, "notify-settings.py"), "dnd", "off"])

    def test_timer_undo_cancels_the_new_one(self):
        self.answers("undo")
        result = self.run_words("timer 10 minutes tea",
                                {"actions": [{"action": "timer", "minutes": 10, "text": "tea"}], "sure": True})
        self.assertEqual(result["result"], "undone")
        self.assertIn(["timers.py", "timer", "0:10:00", "tea"], self.calls())
        self.assertIn(["timers.py", "cancel", "n0"], self.calls())

    def test_launch_uses_the_desktop_id(self):
        self.run_words("open the calculator", {"actions": [{"action": "launch", "app": "calculator"}], "sure": True})
        want = ["uwsm", "app", "--", "org.gnome.Calculator.desktop"]
        import select
        for _ in range(50):                     # detached: the fake writes its call a moment later
            if want in self.calls():            # (time.sleep is stubbed here: select waits)
                break
            select.select([], [], [], 0.05)
        self.assertIn(want, self.calls())

    def test_refused_and_off(self):
        result = self.run_words("run rm -rf", {"actions": [{"action": "shell", "value": "rm -rf ~"}], "sure": True})
        self.assertEqual(result["result"], "refused")
        self.assertFalse([c for c in self.calls() if c[0] not in ("notify-send", "hyprctl")])
        off = self.run_words("pause", conf={"commands": "off", "confirm": False, "language": "auto"})
        self.assertEqual(off["result"], "off")

    def test_failures_are_said(self):
        with mock.patch.object(vc, "hypr_eval", return_value=False):
            result = self.run_words("go to workspace 4")
        self.assertEqual(result["result"], "failed")
        self.assertIn("Hyprland refused it", result["problems"][0])


# -- the CLI hand-off and voice.py's command mode ----------------------------------------
class HandOff(unittest.TestCase):
    def test_read_handoff_deletes_the_file(self):
        os.makedirs(vc.HANDOFF_DIR, exist_ok=True)
        path = os.path.join(vc.HANDOFF_DIR, "command-123.txt")
        with open(path, "w", encoding="utf-8") as h:
            h.write("mueve firefox al escritorio 3")
        self.assertEqual(vc.read_handoff(path), "mueve firefox al escritorio 3")
        self.assertFalse(os.path.exists(path))
        self.assertEqual(vc.read_handoff(path), "")

    def test_run_only_reads_hand_off_files(self):
        # `voice-command.py run FILE` must not read -- or delete -- any other file.
        fd, other = tempfile.mkstemp()
        os.write(fd, b"close the terminal")
        os.close(fd)
        self.addCleanup(os.remove, other)
        with mock.patch.object(vc, "log", lambda t: None):
            self.assertEqual(vc.read_handoff(other), "")
            os.makedirs(vc.HANDOFF_DIR, exist_ok=True)
            sneaky = os.path.join(vc.HANDOFF_DIR, "notes.txt")
            with open(sneaky, "w") as h:
                h.write("x")
            self.addCleanup(os.remove, sneaky)
            self.assertEqual(vc.read_handoff(sneaky), "")
        self.assertTrue(os.path.exists(other) and os.path.exists(sneaky))

    def test_settings_follow_voice_conf(self):
        if os.path.exists(voice.CONF):
            os.remove(voice.CONF)
        self.addCleanup(lambda: os.path.exists(voice.CONF) and os.remove(voice.CONF))
        with mock.patch.dict(sys.modules, {"voice": voice}):
            self.assertEqual(vc.settings(), {"commands": "on", "confirm": False, "language": "auto"})
            voice.write_setting("command_confirm", "on")
            voice.write_setting("command_language", "es")
            voice.write_setting("commands", "off")
            self.assertEqual(vc.settings(), {"commands": "off", "confirm": True, "language": "es"})
        self.assertRaises(ValueError, voice.write_setting, "command_language", "fr")


class VoiceCommandMode(unittest.TestCase):
    def setUp(self):
        if os.path.exists(voice.CONF):
            os.remove(voice.CONF)

    tearDown = setUp

    def test_command_argv(self):
        argv = voice.command_argv("/run/x/command-1.txt", "es", "42")
        self.assertEqual(argv[:6], ["systemd-run", "--user", "--quiet", "--collect", "-p",
                                    "SyslogIdentifier=voice-command"])
        self.assertEqual(argv[-7:], [os.path.join(voice.HERE, "voice-command.py"), "run", "/run/x/command-1.txt",
                                     "--lang", "es", "--replace", "42"])
        self.assertNotIn("--lang", voice.command_argv("/p", "fr"))

    def test_commands_off_records_nothing(self):
        voice.write_setting("commands", "off")
        with mock.patch.object(voice, "notify") as note, mock.patch.object(voice.subprocess, "Popen") as popen:
            d = voice.Daemon()
            self.assertEqual(d.handle({"cmd": "command"}), {"error": "commands off"})
        popen.assert_not_called()
        self.assertIn("off", note.call_args[0][0])

    def test_hand_off_writes_a_private_file(self):
        done = mock.Mock(returncode=0, stdout="", stderr="")
        with mock.patch.object(voice.subprocess, "run", return_value=done) as popen, \
                mock.patch.object(voice, "notify") as note:
            d = voice.Daemon()
            d.note = "9"
            d.hand_off("pausa la música", "es")
        note.assert_not_called()
        argv = popen.call_args[0][0]
        path = argv[argv.index("run") + 1]
        self.addCleanup(os.remove, path)
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        with open(path, encoding="utf-8") as h:
            self.assertEqual(h.read(), "pausa la música")
        self.assertEqual(argv[-4:], ["--lang", "es", "--replace", "9"])

    def test_bar_says_command(self):
        status = voice.bar_status({"state": "recording", "mode": "command", "since": 100}, now=105)
        self.assertIn("command", status["tooltip"])
        self.assertEqual(status["class"], "recording")

    def test_hand_off_that_never_started_leaves_nothing_behind(self):
        failed = mock.Mock(returncode=1, stdout="", stderr="Failed to start transient service unit")
        for result in ({"return_value": failed}, {"side_effect": OSError("no systemd-run")}):
            with mock.patch.object(voice.subprocess, "run", **result) as run, \
                    mock.patch.object(voice, "notify") as note:
                voice.Daemon().hand_off("cierra la ventana", "es")
            path = run.call_args[0][0][run.call_args[0][0].index("run") + 1]
            self.assertFalse(os.path.exists(path))
            self.assertIn("failed", note.call_args[0][0])

    def test_a_recording_started_while_the_last_is_transcribed_keeps_its_mode(self):
        # A dictation is being transcribed, a command recording starts: the
        # dictation's end must not turn the command back into dictation
        # (its words would be typed into the window).
        d = voice.Daemon()
        old = mock.Mock()
        d.rec, d.rec_mode, d.rec_ptt = old, "dictate", False
        d.rec_path = os.path.join(voice.WORK_DIR, "dictation-test.raw")
        os.makedirs(voice.WORK_DIR, exist_ok=True)
        with open(d.rec_path, "wb") as h:
            h.write(b"\0" * int(voice.MIN_RECORD_S * voice.BYTES_PER_S + 10))
        new = mock.Mock()

        def transcribe(path, language=None):
            d.rec, d.rec_mode = new, "command"          # start(mode="command") meanwhile
            return {"text": ""}
        with mock.patch.object(d, "transcribe", transcribe), mock.patch.object(voice, "notify"):
            d.stop()
        self.assertEqual((d.rec, d.rec_mode), (new, "command"))
        self.assertNotEqual(d.state, "idle")

    def test_each_recording_has_its_own_file(self):
        d = voice.Daemon()
        paths = set()
        with mock.patch.object(voice.subprocess, "Popen"), mock.patch.object(voice, "notify"), \
                mock.patch.object(voice, "gaming", return_value=False), \
                mock.patch.object(voice.threading, "Thread"):
            for _ in range(2):
                d.start()
                paths.add(d.rec_path)
                d.rec = None
        for p in paths:
            if os.path.exists(p):
                os.remove(p)
        self.assertEqual(len(paths), 2)


class Hardening(unittest.TestCase):
    """What the adversarial review found."""

    def test_an_action_that_is_not_a_string_is_refused_not_a_crash(self):
        for bad in ({"action": ["move"]}, {"action": {"x": 1}}, {"action": 3}):
            steps, refused = vc.plan([bad], FakeWorld())
            self.assertEqual(steps, [])
            self.assertIn("not an action", refused[0])

    def test_timer_label_numbers_never_add_to_the_time(self):
        timers = helpers.import_script("timers.py")
        step, _ = one({"action": "timer", "minutes": 10, "text": "5 minutes break"})
        rest = " ".join(step["ops"][0][1][3:])
        self.assertEqual(timers.parse_duration(rest), (600, "5 minutes break"))
        step, _ = one({"action": "reminder", "minutes": 20, "text": "2 pills"})
        self.assertEqual(timers.parse_duration(" ".join(step["ops"][0][1][4:])), (1200, "2 pills"))

    def test_only_the_bound_workspaces(self):
        self.assertTrue(one({"action": "workspace", "workspace": 7})[1])
        self.assertTrue(one({"action": "move", "app": "firefox", "workspace": 9})[1])
        world = FakeWorld()
        world.workspaces = lambda: [1, 2, 3, 4, 5, 6, 7, 8]
        self.assertEqual(one({"action": "workspace", "workspace": 8}, world)[0]["action"], "workspace")

    def test_session_names_do_not_start_with_a_dash(self):
        for bad in ("-rf", "--help", ".hidden", ".."):
            self.assertTrue(one({"action": "session-save", "value": bad})[1], bad)
        self.assertEqual(one({"action": "session-save", "value": "Night 2"})[0]["action"], "session-save")

    def test_browser_profiles_and_key_stores_are_secret(self):
        for d in (".mozilla/firefox", ".config/google-chrome", ".aws", ".config/keepassxc", ".ssh"):
            self.assertTrue(vc.looks_secret(os.path.join(vc.HOME, d)), d)
        self.assertFalse(vc.looks_secret(os.path.join(vc.HOME, "Downloads")))

    def test_the_journal_line_has_no_window_titles(self):
        step, _ = one({"action": "move", "app": "firefox", "workspace": 3})
        self.assertIn("News", step["say"])                       # the bubble names it, for you
        self.assertNotIn("News", step["log"])
        self.assertIn("Firefox", step["log"])
        step, _ = one({"action": "side-by-side", "app": "terminal", "app2": "firefox"})
        self.assertNotIn("Atlas", step["log"])

    def test_close_undo_reopens_only_what_was_kept(self):
        kept = {"closed": 2, "record": {"app": "kitty"}}
        older = {"closed": 1, "record": {"app": "firefox"}}
        step, _ = one({"action": "close"})
        world = FakeWorld()
        with mock.patch.object(vc.time, "sleep", lambda s: None):
            world.closed_stack = lambda: [older]                # not kept (a dialog, "close?")
            self.assertEqual(vc.undo_ops(step, [older], world), [])
            world.closed_stack = lambda: [kept, older]
            self.assertEqual(vc.undo_ops(step, [older], world), [("argv", vc.py("closed-windows.py", "reopen"))])
            world.closed_stack = lambda: [kept]                 # the first close ever
            self.assertEqual(len(vc.undo_ops(step, [], world)), 1)

    def test_a_crash_never_leaves_the_bubble_up(self):
        with mock.patch.object(vc, "handle", side_effect=RuntimeError("boom")), \
                mock.patch.object(vc.Notifier, "tell") as tell, mock.patch.object(vc, "log"):
            self.assertRaises(RuntimeError, vc.main, ["text", "pausa"])
        self.assertIn("failed", tell.call_args[0][0])


class Page(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import gi
            gi.require_version("Gtk", "3.0")
            gi.require_version("Gdk", "3.0")
            from settings_pages import voice as page
        except Exception as exc:                                 # no display / GTK
            raise unittest.SkipTest(f"settings_pages.voice not importable: {exc}")
        cls.page = page

    def test_plan_text(self):
        text = self.page.plan_text({"how": "gemma-4-e4b", "refused": ["teleport: not possible"],
                                    "steps": [{"say": "Move Firefox to workspace 3", "confirm": ""},
                                              {"say": "Close Kitty", "confirm": "closes a window"}]})
        self.assertIn("Understood by gemma-4-e4b", text)
        self.assertIn("• Move Firefox to workspace 3", text)
        self.assertIn("asks first: closes a window", text)
        self.assertIn("✗ teleport", text)
        self.assertIn("Understood instantly", self.page.plan_text({"how": "fast", "steps": []}))
        self.assertIn("did not answer", self.page.plan_text(None))


if __name__ == "__main__":
    unittest.main()
