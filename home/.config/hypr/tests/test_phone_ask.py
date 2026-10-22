"""phone-ask.py: asking the desktop from the phone. KDE Connect's run-command
config (QSettings INI) read and written without losing anyone else's
commands, the listener's test of a Notify call (only kdeconnectd's own
"text shared" event counts, never a mirrored phone notification), the
trusted-device / rate-limit / one-at-a-time checks, the action allow-list
judging the assistant's pending plan, the reply over kdeconnect-cli, and the
privacy.conf switches (off as shipped); Settings' section helpers.

Hermetic: a fake phone module stands in for kdeconnect-cli / D-Bus (it
records what would be sent), a fake assistant for the local model, the
run-command files live in a scratch folder; nothing is sent, nothing runs."""
import json
import os
import tempfile
import types
import unittest
from unittest import mock

import helpers

pa = helpers.import_script("phone-ask.py")
ps = helpers.import_script("privacy_settings.py")

PHONE = {"id": "0cdda76f_phone", "name": "💩", "reachable": True}
OTHER = {"id": "abcd1234_tablet", "name": "Tablet", "reachable": False}


class FakePhone:
    """kdeconnect-cli as phone.py's run() would call it: recorded, not run."""
    CLI = "kdeconnect-cli"

    def __init__(self, devices=(PHONE, OTHER), ok=True, clip=""):
        self._devices, self.ok, self.clip, self.calls = list(devices), ok, clip, []

    def devices(self):
        return [dict(d) for d in self._devices]

    def run(self, *argv, timeout=10):
        self.calls.append(argv)
        return "" if self.ok else None

    def clipboard_text(self):
        return self.clip


class FakeAssistant:
    """assistant.py's run_turn / confirm / take_pending, no model."""
    WORDS = {"en": {"waiting": "⏸ Not done yet: wait for Confirm."}, "es": {"waiting": "⏸ Aún no."}}

    def __init__(self, turn, enabled="on"):
        self.turn, self.enabled = turn, enabled
        self.confirmed, self.cancelled, self.remembered, self.conf_seen = [], [], [], None

    def settings(self):
        return {"enabled": self.enabled, "confirm": "risky", "tool_screen": "on", "tool_actions": "on",
                "history_days": 7}

    def run_turn(self, question, conf, who="assistant"):
        self.conf_seen, self.who_seen = conf, who
        return dict(self.turn, question=question)

    def remember(self, turn, conf):
        self.remembered.append(turn["question"])

    def confirm(self, pid):
        self.confirmed.append(pid)
        return ["pause the music"], [], []

    def take_pending(self, pid):
        self.cancelled.append(pid)
        return {}


def turn(answer="ok", pending=None, lang="en"):
    return {"answer": answer, "pending": pending, "done": [], "lang": lang, "steps": []}


class Ini(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(dir=helpers.SCRATCH)
        self.path = os.path.join(self.dir, "config")

    def test_escape_round_trip(self):
        for text in ('@ByteArray({"a":{"command":"echo \\"hi\\"","name":"x"}})', "plain", 'back\\slash "q"'):
            self.assertEqual(pa.ini_unescape(pa.ini_escape(text)), text)

    def test_reads_what_kde_connect_writes(self):
        with open(self.path, "w") as h:
            h.write('[General]\ncommands="@ByteArray({\\"{1b2c}\\":{\\"command\\":\\"systemctl suspend\\",'
                    '\\"name\\":\\"Suspend\\"}})"\n')
        self.assertEqual(pa.read_commands(self.path), {"{1b2c}": {"command": "systemctl suspend", "name": "Suspend"}})

    def test_missing_or_broken_is_empty(self):
        self.assertEqual(pa.read_commands(self.path), {})
        with open(self.path, "w") as h:
            h.write("[General]\ncommands=@ByteArray(not json)\n")
        self.assertEqual(pa.read_commands(self.path), {})

    def test_write_keeps_the_rest_of_the_file(self):
        with open(self.path, "w") as h:
            h.write("[General]\nother=1\ncommands=\"@ByteArray({})\"\n\n[Extra]\nkey=v\n")
        pa.write_commands(self.path, {"k": {"name": "N", "command": "c"}})
        with open(self.path) as h:
            text = h.read()
        self.assertIn("other=1", text)
        self.assertIn("[Extra]\nkey=v", text)
        self.assertEqual(text.count("commands="), 1)
        self.assertEqual(pa.read_commands(self.path), {"k": {"name": "N", "command": "c"}})

    def test_write_new_file(self):
        pa.write_commands(self.path, {"k": {"name": "Ñandú", "command": "c"}})
        with open(self.path) as h:
            self.assertTrue(h.read().startswith("[General]\ncommands=\"@ByteArray("))
        self.assertEqual(pa.read_commands(self.path)["k"]["name"], "Ñandú")


class Commands(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(dir=helpers.SCRATCH)
        self.patch = mock.patch.object(pa, "KDECONNECT", self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_entries_are_fixed_words(self):
        entries = pa.preset_entries(PHONE["id"], ["lock", "nope", "build"])
        self.assertEqual(sorted(entries), ["hypr-desktop-ask-build", "hypr-desktop-ask-lock"])
        cmd = entries["hypr-desktop-ask-lock"]["command"]
        self.assertTrue(cmd.endswith(f"preset lock --device {PHONE['id']}"))
        self.assertIn(pa.SELF, cmd)

    def test_install_keeps_others_and_uninstall_removes_only_ours(self):
        path = pa.commands_path(PHONE["id"])
        pa.write_commands(path, {"mine": {"name": "Suspend", "command": "systemctl suspend"},
                                 "hypr-desktop-ask-old": {"name": "stale", "command": "x"}})
        conf = dict(pa.DEFAULTS, presets="lock,pause")
        self.assertEqual(pa.install(conf, [PHONE]), [PHONE["name"]])
        cmds = pa.read_commands(path)
        self.assertEqual(sorted(cmds), ["hypr-desktop-ask-lock", "hypr-desktop-ask-pause", "mine"])
        self.assertEqual(pa.installed(PHONE["id"]), ["lock", "pause"])
        pa.uninstall([PHONE])
        self.assertEqual(list(pa.read_commands(path)), ["mine"])

    def test_device_choice(self):
        fake = FakePhone()
        with mock.patch.object(pa, "phone", lambda: fake):
            self.assertEqual([d["id"] for d in pa.target_devices(dict(pa.DEFAULTS))], [PHONE["id"], OTHER["id"]])
            self.assertEqual([d["id"] for d in pa.target_devices(dict(pa.DEFAULTS, device=OTHER["id"]))],
                             [OTHER["id"]])


def notify_msg(event="textShareReceived", sender=":1.7", app="kdeconnect", title="Shared text from 💩 copied",
               body="? did the build finish"):
    hints = {"urgency": {"type": "y", "data": 1}}
    if event:
        hints["x-kde-eventId"] = {"type": "s", "data": event}
    if app:
        hints["x-kde-appname"] = {"type": "s", "data": app}
    return {"type": "method_call", "sender": sender, "interface": "org.freedesktop.Notifications",
            "member": "Notify", "payload": {"type": "susssasa{sv}i",
                                            "data": ["KDE Connect", 0, "", title, body, [], hints, -1]}}


class Listener(unittest.TestCase):
    PIDS = {":1.7": 4242, ":1.9": 999}

    def event(self, msg):
        return pa.shared_text_event(msg, lambda: 4242, self.PIDS.get)

    def test_kdeconnects_shared_text(self):
        self.assertEqual(self.event(notify_msg(body="? a &amp; <b>b</b>")), ("Shared text from 💩 copied", "? a & b"))

    def test_mirrored_phone_notification_never_counts(self):
        # An SMS that reads "? lock": kdeconnectd posts it too, as another event.
        self.assertIsNone(self.event(notify_msg(event="notification", body="? lock")))
        self.assertIsNone(self.event(notify_msg(event=None)))

    def test_only_kdeconnectd_itself(self):
        self.assertIsNone(self.event(notify_msg(sender=":1.9")))
        self.assertIsNone(self.event(notify_msg(app="someapp")))
        self.assertIsNone(pa.shared_text_event(notify_msg(), lambda: None, self.PIDS.get))

    def test_other_messages(self):
        msg = notify_msg()
        msg["member"] = "CloseNotification"
        self.assertIsNone(self.event(msg))
        msg = notify_msg()
        msg["payload"]["data"] = ["x"]
        self.assertIsNone(self.event(msg))

    def test_device_in_title(self):
        paired = [PHONE, OTHER, {"id": "x", "name": "💩 2", "reachable": True}]
        self.assertEqual(pa.device_in_title("Shared text from 💩 2 copied", paired)["id"], "x")
        self.assertEqual(pa.device_in_title("Shared text from 💩 copied", paired)["id"], PHONE["id"])
        self.assertIsNone(pa.device_in_title("Shared text from Mallory copied", paired))
        # two unrelated names in one title: which one sent it is not guessed
        two = [{"id": "a", "name": "Shared", "reachable": True}, {"id": "b", "name": "Tab", "reachable": True}]
        self.assertIsNone(pa.device_in_title("Shared text from Tab copied to clipboard", two))

    def test_prefix_and_route(self):
        self.assertEqual(pa.strip_prefix("  ? what's up ", "?"), "what's up")
        self.assertIsNone(pa.strip_prefix("an ordinary share", "?"))
        self.assertIsNone(pa.strip_prefix("?", "?"))
        self.assertEqual(pa.strip_prefix("DESK: hola", "desk:"), "hola")
        self.assertEqual(len(pa.strip_prefix("?" + "x" * 5000, "?")), pa.QUESTION_MAX)
        conf = dict(pa.DEFAULTS)
        self.assertEqual(pa.route("¿Pausa?", conf), ("pause", ""))
        self.assertEqual(pa.route("bloquear", conf)[0], "lock")
        self.assertEqual(pa.route("pantalla", conf)[0], "screen")
        self.assertEqual(pa.route("lock the door at 5", conf), ("assistant", "lock the door at 5"))
        self.assertEqual(pa.route("lock", dict(conf, presets="brief")), ("assistant", "lock"))

    def test_take_question_from_clipboard_and_clears_it(self):
        fake = FakePhone(clip="? what's on my screen")
        listener = pa.Listener.__new__(pa.Listener)
        spawned = []

        class Proc:
            def __init__(self, argv, **_kw):
                spawned.append(argv)

            def communicate(self, data, timeout=None):
                spawned.append(data)
        with mock.patch.object(pa, "phone", lambda: fake), mock.patch.object(pa, "switches", lambda: (True, False)), \
                mock.patch.object(pa, "settings", lambda: dict(pa.DEFAULTS)), \
                mock.patch.object(pa.subprocess, "Popen", Proc):
            listener.take("Shared text from 💩 copied", "")        # the body may be empty: the clipboard has it
        self.assertIn(("wl-copy", "--clear"), fake.calls)
        self.assertEqual(spawned[0][2:], ["ask", "--device", PHONE["id"], "--source", "text", "-"])
        self.assertEqual(spawned[1], "what's on my screen")

    def test_take_ignores_ordinary_share_and_strangers(self):
        listener = pa.Listener.__new__(pa.Listener)
        with mock.patch.object(pa, "switches", lambda: (True, False)), \
                mock.patch.object(pa, "settings", lambda: dict(pa.DEFAULTS)), \
                mock.patch.object(pa.subprocess, "Popen", side_effect=AssertionError("ran")), \
                mock.patch.object(pa, "log"):
            fake = FakePhone(clip="just a note")
            with mock.patch.object(pa, "phone", lambda: fake):
                listener.take("Shared text from 💩 copied", "just a note")
                listener.take("Shared text from Mallory copied", "? lock")
            self.assertEqual(fake.calls, [])
        with mock.patch.object(pa, "switches", lambda: (False, False)), \
                mock.patch.object(pa.subprocess, "Popen", side_effect=AssertionError("ran")):
            listener.take("Shared text from 💩 copied", "? lock")      # off: nothing


class Checks(unittest.TestCase):
    def test_trusted(self):
        conf = dict(pa.DEFAULTS)
        paired = [PHONE, OTHER]
        self.assertEqual(pa.trusted(PHONE["id"], conf, paired)[0]["id"], PHONE["id"])
        self.assertEqual(pa.trusted("stranger", conf, paired), (None, "not a paired device"))
        self.assertEqual(pa.trusted(OTHER["id"], conf, paired), (None, "not reachable now"))
        self.assertEqual(pa.trusted(PHONE["id"], dict(conf, device=OTHER["id"]), paired)[1],
                         "not the device chosen in Settings")

    def test_rate_limit(self):
        path = os.path.join(tempfile.mkdtemp(dir=helpers.SCRATCH), "recent.json")
        conf = dict(pa.DEFAULTS, limit=3)
        self.assertEqual([pa.rate_ok(conf, 1000 + i, path) for i in range(4)], [True, True, True, False])
        self.assertTrue(pa.rate_ok(conf, 1000 + pa.RATE_WINDOW_S + 1, path))    # the window moved on

    def test_one_at_a_time(self):
        first = pa.busy_lock()
        try:
            self.assertIsNone(pa.busy_lock())
        finally:
            first.close()
        again = pa.busy_lock()
        self.assertIsNotNone(again)
        again.close()

    def test_settings(self):
        path = os.path.join(tempfile.mkdtemp(dir=helpers.SCRATCH), "settings.json")
        self.assertEqual(pa.settings(path)["reply"], "ping")
        self.assertEqual(pa.set_setting("limit", "5", path), 5)
        self.assertEqual(pa.set_setting("allow", "media, close", path), "media,close")
        self.assertEqual(pa.set_setting("allow", "none", path), "")
        for key, value in (("limit", "7"), ("allow", "rm-rf"), ("prefix", "!"), ("presets", "x"),
                           ("device", "a b"), ("nope", "1")):
            with self.assertRaises(ValueError):
                pa.set_setting(key, value, path)
        self.assertEqual(pa.settings(path)["limit"], 5)

    def test_unknown_name_never_widens_the_allow_list(self):
        path = os.path.join(tempfile.mkdtemp(dir=helpers.SCRATCH), "settings.json")
        with open(path, "w") as handle:     # "gone-away": an action the catalog no longer has
            json.dump({"allow": "media,gone-away", "presets": "lock,nope"}, handle)
        conf = pa.settings(path)
        self.assertEqual((conf["allow"], conf["presets"]), ("media", "lock"))

    def test_shipped_defaults_refuse_risky(self):
        for risky in pa.RISKY:
            self.assertNotIn(risky, pa.ALLOW_DEFAULT)


class Answers(unittest.TestCase):
    def test_phone_conf(self):
        base = {"confirm": "risky", "tool_screen": "on", "tool_actions": "on"}
        conf = pa.phone_conf(base, False, [])
        self.assertEqual((conf["confirm"], conf["tool_screen"], conf["tool_actions"]), ("all", "off", "off"))
        self.assertEqual(pa.phone_conf(base, True, ["media"])["tool_screen"], "on")
        self.assertEqual(base["confirm"], "risky")      # the assistant's own settings untouched

    def test_judge(self):
        plan = {"actions": [{"action": "media", "value": "pause"}, {"action": "close"}]}
        self.assertEqual(pa.judge_pending(plan, ["media"]), (False, ["close"]))
        self.assertEqual(pa.judge_pending(plan, ["media", "close"]), (True, []))
        self.assertEqual(pa.judge_pending({"actions": []}, ["media"]), (False, []))

    def test_allowed_action_is_done(self):
        fa = FakeAssistant(turn("When you confirm, it pauses.\n\n⏸ Not done yet: wait for Confirm.",
                                {"id": "abc123", "actions": [{"action": "media", "value": "pause"}]}))
        with mock.patch.object(pa, "assistant", lambda: fa):
            text, done, refused = pa.ask_assistant("pause the music", False, ["media"])
        self.assertEqual(fa.confirmed, ["abc123"])
        self.assertEqual((text, done, refused), ("Done: pause the music", ["pause the music"], []))
        self.assertEqual(fa.conf_seen["confirm"], "all")
        self.assertEqual(fa.conf_seen["tool_screen"], "off")
        self.assertEqual(fa.who_seen, "phone")          # folder access: the phone's own grants, no prompt

    def test_other_action_is_cancelled(self):
        fa = FakeAssistant(turn("Will close it.", {"id": "abc124", "actions": [{"action": "close", "app": "x"}]}))
        with mock.patch.object(pa, "assistant", lambda: fa):
            text, done, refused = pa.ask_assistant("close firefox", False, ["media"])
        self.assertEqual((fa.confirmed, fa.cancelled, refused), ([], ["abc124"], ["close"]))
        self.assertIn("Not done from the phone: close", text)

    def test_dry_run_neither_does_nor_remembers(self):
        fa = FakeAssistant(turn("x", {"id": "abc125", "actions": [{"action": "media"}], "lines": ["Pause"]}))
        with mock.patch.object(pa, "assistant", lambda: fa):
            text, _done, _refused = pa.ask_assistant("pause", False, ["media"], dry_run=True)
        self.assertEqual((fa.confirmed, fa.cancelled, fa.remembered), ([], ["abc125"], []))
        self.assertIn("Dry run", text)

    def test_assistant_off(self):
        with mock.patch.object(pa, "assistant", lambda: FakeAssistant(turn(), enabled="off")):
            self.assertIn("switched off", pa.ask_assistant("hi", False, [])[0])

    def test_no_action_plan_is_not_called_a_dry_run(self):
        fa = FakeAssistant(turn("x", {"id": "abc126", "actions": [], "lines": []}))
        with mock.patch.object(pa, "assistant", lambda: fa):
            text = pa.ask_assistant("hm", False, ["media"])[0]
        self.assertNotIn("Dry run", text)
        self.assertIn("Nothing was done", text)

    def test_screen_off_hides_remembered_screen_text(self):
        rows = [{"source": "screen", "text": "secret on screen", "thumbnail": "/t.png"},
                {"source": "clipboard", "text": "copied", "url": "https://x"}]

        def search(name, args, turn_):
            return {"mode": "words", "memories": list(rows), "files": [{"path": "/t.png"}, {"path": "https://x"}]}

        fa = FakeAssistant(turn("ok"))
        fa.RUN = {"search_memory": search}
        got = {}

        def run_turn(question, conf, who="assistant"):
            got["all"] = fa.RUN["search_memory"]("search_memory", {"query": "q"}, None)
            got["screen"] = fa.RUN["search_memory"]("search_memory", {"query": "q", "source": "screen"}, None)
            return dict(fa.turn, question=question)

        fa.run_turn = run_turn
        with mock.patch.object(pa, "assistant", lambda: fa):
            pa.ask_assistant("what was on my screen", False, [])
        self.assertEqual([r["source"] for r in got["all"]["memories"]], ["clipboard"])
        self.assertEqual(got["all"]["files"], [{"path": "https://x"}])
        self.assertIn("note", got["screen"])
        self.assertIs(fa.RUN["search_memory"], search)     # put back after the question
        with mock.patch.object(pa, "assistant", lambda: fa):
            pa.ask_assistant("what was on my screen", True, [])
        self.assertEqual(len(got["all"]["memories"]), 2)    # allowed: untouched

    def test_lock_works_outside_a_login_session(self):
        calls = []

        def fake_run(argv, **kw):
            calls.append(argv)
            return types.SimpleNamespace(returncode=1 if argv[0] == "pidof" else 0)

        with mock.patch.object(pa.subprocess, "run", fake_run):
            self.assertEqual(pa.do_lock(), "Locked the desktop.")
        self.assertEqual(calls[-1], ["loginctl", "lock-session", "auto"])

    def test_screen_needs_the_switch(self):
        text, _d, refused = pa.answer_for("screen", "q", dict(pa.DEFAULTS), False)
        self.assertEqual(refused, ["screen"])
        self.assertIn("off", text)

    def test_reply_clipped_and_sent_the_chosen_way(self):
        fake = FakePhone()
        with mock.patch.object(pa, "phone", lambda: fake):
            self.assertTrue(pa.send_reply(PHONE, "x" * 5000, dict(pa.DEFAULTS, reply="both")))
        self.assertEqual([c[3] for c in fake.calls], ["--ping-msg", "--share-text"])
        self.assertEqual(len(fake.calls[0][4]), pa.REPLY_MAX)
        self.assertEqual(fake.calls[0][:3], ("kdeconnect-cli", "-d", PHONE["id"]))


class Handle(unittest.TestCase):
    def run_handle(self, on=True, device=PHONE["id"], fake=None, kind="assistant", conf=None):
        fake = fake or FakePhone()
        fa = FakeAssistant(turn("It finished at 10:02."))
        self.logged = []
        with mock.patch.object(pa, "phone", lambda: fake), mock.patch.object(pa, "assistant", lambda: fa), \
                mock.patch.object(pa, "switches", lambda: (on, False)), \
                mock.patch.object(pa, "rate_ok", lambda _c: True), \
                mock.patch.object(pa, "log", self.logged.append):
            code, text = pa.handle(device, kind, "did my build finish", "text", conf=conf or dict(pa.DEFAULTS))
        return code, text, fake

    def test_answers_the_trusted_phone(self):
        code, text, fake = self.run_handle()
        self.assertEqual(code, 0)
        self.assertEqual(fake.calls, [("kdeconnect-cli", "-d", PHONE["id"], "--ping-msg", "It finished at 10:02.")])
        self.assertTrue(self.logged[0].startswith("text question (19 chars) from 💩"))
        self.assertNotIn("build", " ".join(self.logged))         # never the words, never the answer
        self.assertNotIn("10:02", " ".join(self.logged))

    def test_refused(self):
        for kwargs, why in (({"on": False}, "off"), ({"device": "stranger"}, "not a paired device"),
                            ({"device": OTHER["id"]}, "not reachable now"), ({"device": None}, "no device")):
            code, _text, fake = self.run_handle(**kwargs)
            self.assertEqual(code, 3, kwargs)
            self.assertEqual(fake.calls, [], kwargs)
            self.assertIn(why, self.logged[0])

    def test_rate_limited_says_so_once(self):
        fake = FakePhone()
        with mock.patch.object(pa, "phone", lambda: fake), mock.patch.object(pa, "switches", lambda: (True, False)), \
                mock.patch.object(pa, "rate_ok", lambda _c: False), mock.patch.object(pa, "log"):
            code, _ = pa.handle(PHONE["id"], "assistant", "q", "text", conf=dict(pa.DEFAULTS))
        self.assertEqual(code, 4)
        self.assertIn("Too many questions", fake.calls[0][4])


class Privacy(unittest.TestCase):
    def test_off_as_shipped(self):
        self.assertFalse(ps.phone_ask_on({}))
        self.assertFalse(ps.phone_ask_screen_on({}))
        self.assertTrue(ps.phone_ask_on({"phone_ask": "on"}))

    def test_cli_sets_the_keys(self):
        path = os.path.join(tempfile.mkdtemp(dir=helpers.SCRATCH), "privacy.conf")
        with mock.patch.object(ps, "CONF", path):
            ps.main(["phone", "ask", "on"])
            ps.main(["phone", "screen", "on"])
            conf = ps.load(path)
        self.assertTrue(ps.phone_ask_on(conf) and ps.phone_ask_screen_on(conf))


class SettingsSection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import settings_pages._phone_ask as section
        except Exception as err:    # noqa: BLE001 -- no GTK in this environment
            raise unittest.SkipTest(f"GTK: {err}")
        cls.s = section

    def test_toggled(self):
        self.assertEqual(self.s.toggled("media,volume", "close", True), "media,volume,close")
        self.assertEqual(self.s.toggled("media,volume", "media", False), "volume")
        self.assertEqual(self.s.toggled("media", "media", False), "none")

    def test_how_text(self):
        data = {"on": True, "listener": False, "settings": dict(pa.DEFAULTS),
                "presets": {n: p[0] for n, p in pa.PRESETS.items()},
                "devices": [dict(PHONE, chosen=True, installed=["lock"])]}
        text = self.s.how_text(data)
        self.assertIn("Lock the desktop", text)
        self.assertIn("phone-ask.service", text)
        self.assertIn("Off", self.s.how_text(dict(data, on=False)))
        self.assertIn("No phone paired", self.s.how_text(dict(data, devices=[])))
        self.assertEqual(self.s.action_caption("close", pa.RISKY), "close (risky)")


if __name__ == "__main__":
    unittest.main()
