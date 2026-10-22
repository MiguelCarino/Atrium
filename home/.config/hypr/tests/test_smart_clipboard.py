"""smart-clipboard.py: the rules that recognise a copy, the ones that keep
secrets out, the quiet rules and the hook's refusals. No clipboard, no
window, no service: the hook's subprocess calls are stubbed."""
import io
import json
import os
import unittest
from unittest import mock

from helpers import import_script

sc = import_script("smart-clipboard.py")


def kind(text):
    found = sc.detect(text)
    return found.kind if found else None


class Kinds(unittest.TestCase):
    def test_each_kind(self):
        cases = {
            "https://example.com/a?b=1": "url",
            "www.example.org": "url",
            "someone@example.com": "email",
            "mailto:a.b@mail.example.mx": "email",
            "+52 55 1234 5678": "phone",
            "(55) 1234 5678": "phone",
            "555-1234": "phone",
            "Av. Reforma 222, Col. Juárez, 06600 CDMX": "address",
            "221B Baker Street\nLondon NW1 6XE": "address",
            "#00f0ff": "colour",
            "#abc": "colour",
            "rgb(0 240 255 / 50%)": "colour",
            "hsl(180, 100%, 50%)": "colour",
            "1Z999AA10123456784": "tracking",
            "RR123456785MX": "tracking",
            "21 Oct 2026 15:30": "date",
            "2026-10-21": "date",
            "21/10/2026": "date",
            "21 de octubre de 2026 a las 5pm": "date",
            "October 21, 2026 at 3:30 pm": "date",
            "12*(3+4)/2": "math",
            "2^10": "math",
            "1,250 x 3": "math",
            '{"a": 1, "b": [2, 3]}': "json",
            "[1, 2, 3, 4]": "json",
            "Traceback (most recent call last):\n  File \"x.py\", line 3, in <module>\n"
            "NameError: name 'foo' is not defined": "error",
            "TypeError: Cannot read properties of undefined (reading 'x')\n"
            "    at main (/app/index.js:10:5)": "error",
        }
        for text, want in cases.items():
            with self.subTest(text=text):
                self.assertEqual(kind(text), want)

    def test_nothing(self):
        for text in ("hello world", "12", "2026", "10-20", "a paragraph that mentions https://x.org once",
                     "", "   ", "#zzz", "rgb(300, 0, 0)", "1Z999AA10123456785", "RR123456789MX",
                     "123456789012", "{}", "2/0"):
            with self.subTest(text=text):
                self.assertIsNone(kind(text))

    def test_path_exists_and_secret(self):
        here = os.path.abspath(__file__)
        self.assertEqual(kind(here), "path")
        self.assertIsNone(kind("/no/such/file/anywhere"))
        with mock.patch.object(sc, "secret_path", return_value=True):
            self.assertIsNone(kind(here))

    def test_url_trackers_offered_off(self):
        found = sc.detect("https://example.com/p?id=3&utm_source=x&fbclid=y")
        labels = {a[0]: a[2] for a in found.actions}
        self.assertEqual(labels["copy"], "https://example.com/p?id=3")
        self.assertEqual(len(sc.detect("https://example.com/p?id=3").actions), 1)

    def test_at_most_three_actions(self):
        for text in ("+52 55 1234 5678", "#00f0ff", '{"a": [1, 2]}', "1Z999AA10123456784"):
            self.assertLessEqual(len(sc.detect(text).actions), 3)


class Values(unittest.TestCase):
    def test_compute(self):
        self.assertEqual(sc.compute("12*(3+4)/2"), 42)
        self.assertEqual(sc.compute("2^10"), 1024)
        self.assertEqual(sc.compute("1,250 × 3"), 3750)
        self.assertEqual(sc.compute("7 / 2"), 3.5)
        self.assertEqual(sc.compute("0.1+0.2"), 0.3)
        self.assertIsNone(sc.compute("9**9999"))
        self.assertIsNone(sc.compute("__import__('os')"))
        self.assertIsNone(sc.compute("1/0"))

    def test_colour(self):
        self.assertEqual(sc.parse_colour("#00f0ff"), (0, 240, 255, 1.0))
        self.assertEqual(sc.parse_colour("#0f08"), (0, 255, 0, 0.533))
        self.assertEqual(sc.parse_colour("rgba(255, 0, 0, 0.5)"), (255, 0, 0, 0.5))
        self.assertEqual(sc.parse_colour("hsl(0 100% 50%)"), (255, 0, 0, 1.0))
        self.assertEqual(sc.hex_of(0, 240, 255, 0.5), "#00f0ff80")

    def test_dates(self):
        today = sc.dt.date(2026, 10, 21)
        when, has_time, rest = sc.parse_date("Dentist 3 Nov 10:30", today)
        self.assertEqual((when, has_time, rest), (sc.dt.datetime(2026, 11, 3, 10, 30), True, "Dentist"))
        when, has_time, _ = sc.parse_date("12/25/2026", today)          # cannot be day-first
        self.assertEqual((when.month, when.day, has_time), (12, 25, False))
        when, _, _ = sc.parse_date("05/04/2026", today)                 # day-first by default
        self.assertEqual((when.day, when.month), (5, 4))
        self.assertIsNone(sc.parse_date("31/02/2026", today))
        payload = json.loads(sc.detect("2026-10-21 18:00").actions[0][2])
        self.assertEqual(payload, {"title": "Reminder", "start": "2026-10-21T18:00", "all_day": False})

    def test_carriers(self):
        self.assertEqual(sc.carrier_of("1Z999AA10123456784")[0], "UPS")
        self.assertEqual(sc.carrier_of("RR123456785US")[0], "USPS")
        self.assertTrue(sc.carrier_of("RR123456785MX")[0].startswith("Postal"))
        self.assertEqual(sc.carrier_of("JJD000390007827179630")[0], "DHL")
        self.assertIsNone(sc.carrier_of("123456789012")[0])


class Secrets(unittest.TestCase):
    def test_never_acted_on(self):
        for text in ("4111 1111 1111 1111", "4111-1111-1111-1111", "5500005555555559",
                     "DE89370400440532013000", "GB82 WEST 1234 5698 7654 32",
                     "002010077777777771",                              # a CLABE
                     "Hunter2Password!", "xK9#mQ2$vL7p", "password: hunter2", "token=abcdef",
                     "API_KEY: x", "ghp_" + "a" * 36, "sk-" + "b" * 40, "AKIA" + "C" * 16,
                     "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc",
                     "-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n-----END OPENSSH PRIVATE KEY-----"):
            with self.subTest(text=text):
                self.assertTrue(sc.looks_secret(text))
                self.assertIsNone(sc.detect(text))

    def test_not_secret(self):
        for text in ("1Z999AA10123456784", "hello world", "https://example.com/a?B=1", "#00f0ff",
                     "+52 55 1234 5678", "2026-10-21", "someone@example.com", "RR123456785MX"):
            with self.subTest(text=text):
                self.assertFalse(sc.looks_secret(text))

    def test_private_focus(self):
        conf = {"activity_exclude": "org.telegram.desktop"}
        self.assertTrue(sc.private_focus({"class": "org.keepassxc.KeePassXC", "title": "db"}, conf))
        self.assertTrue(sc.private_focus({"class": "Bitwarden", "title": "Vault"}, conf))
        self.assertTrue(sc.private_focus({"class": "firefox", "title": "Mozilla Firefox Private Browsing"}, conf))
        self.assertTrue(sc.private_focus({"class": "org.telegram.desktop", "title": "chat"}, conf))
        self.assertFalse(sc.private_focus({"class": "kitty", "title": "~"}, conf))


class Quiet(unittest.TestCase):
    def test_rate(self):
        state = {}
        self.assertTrue(sc.rate_ok(state, "a", 1000))
        self.assertFalse(sc.rate_ok(state, "b", 1001))             # too soon after the last
        self.assertTrue(sc.rate_ok(state, "b", 1000 + sc.MIN_GAP_S))
        self.assertFalse(sc.rate_ok(state, "a", 1100))             # the same copy again
        self.assertTrue(sc.rate_ok(state, "a", 1000 + sc.REPEAT_S + 10))
        state["own"] = ["c"]
        self.assertFalse(sc.rate_ok(state, "c", 99999))            # our own copy

    def test_seen_is_bounded(self):
        state = {}
        for i in range(sc.SEEN_KEEP + 50):
            sc.rate_ok(state, str(i), 10_000 + i * sc.MIN_GAP_S)
        self.assertEqual(len(state["seen"]), sc.SEEN_KEEP)

    def test_kinds_on_defaults_and_conf(self):
        on = sc.kinds_on({})
        self.assertFalse(on["url"])
        self.assertTrue(on["colour"])
        on = sc.kinds_on({"smartclip_url": "on", "smartclip_math": "off"})
        self.assertTrue(on["url"])
        self.assertFalse(on["math"])


class Hook(unittest.TestCase):
    def setUp(self):
        for path in (sc.STATE,):
            if os.path.exists(path):
                os.remove(path)
        patches = [mock.patch.object(sc, "_watcher_age", return_value=100),
                   mock.patch.object(sc, "private_focus", return_value=False),
                   mock.patch.object(sc, "quiet_now", return_value=False),
                   mock.patch.object(sc.privacy_settings, "load", return_value={})]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.popen = mock.patch.object(sc.subprocess, "Popen").start()
        self.addCleanup(mock.patch.stopall)

    def run_hook(self, text, state="data"):
        return sc.hook(io.BytesIO(text.encode()), {"CLIPBOARD_STATE": state})

    def test_shows_a_card_through_stdin(self):
        found = self.run_hook("#00f0ff")
        self.assertEqual(found.kind, "colour")
        argv = self.popen.call_args[0][0]
        self.assertEqual(argv[-1], "toast")
        self.assertNotIn("#00f0ff", " ".join(argv))                # never on the command line
        sent = json.loads(self.popen.return_value.stdin.write.call_args[0][0])
        self.assertEqual(sent["text"], "#00f0ff")

    def test_refusals(self):
        self.assertIsNone(self.run_hook("#00f0ff", state="sensitive"))
        self.assertIsNone(self.run_hook("4111 1111 1111 1111"))
        self.assertIsNone(self.run_hook("https://example.com"))     # links are off by default
        with mock.patch.object(sc, "private_focus", return_value=True):
            self.assertIsNone(self.run_hook("#123456"))
        with mock.patch.object(sc, "_watcher_age", return_value=0.5):
            self.assertIsNone(self.run_hook("#654321"))
        self.popen.assert_not_called()

    def test_repeat_is_quiet(self):
        self.assertIsNotNone(self.run_hook("12*(3+4)/2"))
        self.assertIsNone(self.run_hook("12*(3+4)/2"))


class Actions(unittest.TestCase):
    def test_copy_remembers_own(self):
        with mock.patch.object(sc.subprocess, "run") as run:
            self.assertEqual(sc.run_action("copy", "42", "6*7"), "Copied.")
        self.assertEqual(run.call_args[0][0], ["wl-copy"])
        self.assertIn(sc.digest("42"), sc.read_state()["own"])

    def test_open_and_ask(self):
        with mock.patch.object(sc.subprocess, "Popen") as popen:
            sc.run_action("open", "https://example.com", "")
            self.assertEqual(popen.call_args[0][0], ("xdg-open", "https://example.com"))
            sc.run_action("ask", "", "Traceback ...")
            argv = popen.call_args[0][0]
            self.assertEqual(argv[1:3], (sc.SCREEN_ASK, "text"))
            popen.return_value.stdin.write.assert_called_with(b"Traceback ...")


if __name__ == "__main__":
    unittest.main()


class ReviewFixes(unittest.TestCase):
    """What the review found: no-space shapes taken for passwords, the
    phone.py path shadowed by the phone regex, secrets that slipped by."""

    def test_no_space_shapes_are_not_passwords(self):
        self.assertEqual(kind("rgb(0,240,255)"), "colour")
        self.assertEqual(kind("hsl(180,100%,50%)"), "colour")
        self.assertEqual(kind('{"a":1,"b":[2,3]}'), "json")
        self.assertEqual(kind("2026-10-21T15:30"), "date")
        self.assertEqual(kind("tel:5512345678"), "phone")

    def test_passwords_still_are(self):
        for text in ("Hunter2!xyz9", "aB3$efgh12", "Tr0ub4dor&3x"):
            self.assertTrue(sc.looks_secret(text), text)

    def test_more_secrets(self):
        for text in ('{"password": "hunter2xx"}', "{'api_key': 'abc'}",
                     "https://user:hunter2@example.com/x", "postgres://me:pw@db/x",
                     "Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123"):
            self.assertTrue(sc.looks_secret(text), text)
            self.assertIsNone(sc.detect(text), text)
        self.assertFalse(sc.looks_secret("https://example.com/a@b"))

    def test_phone_action_spawns_phone_py(self):
        self.assertTrue(sc.PHONE.endswith("phone.py"))
        with mock.patch.object(sc, "copy"), mock.patch.object(sc, "spawn") as spawn:
            sc.run_action("phone", "+525512345678", "")
        self.assertEqual(spawn.call_args[0][1], sc.PHONE)
