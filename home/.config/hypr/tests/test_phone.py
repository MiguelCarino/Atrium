"""phone.py's handoff: sign-in codes found in notification text, the LZ4 /
mozLz4 decoder and the Firefox and Chromium session readers behind "open this
page on the phone", the files-copied-in-Files list, and the watcher's photo
and link handling; privacy_settings.py's phone_codes switch (off as shipped).

Hermetic: the session files are built here, the watcher's notifications and
clipboard calls are stubbed, photos move between scratch folders; no
kdeconnect-cli, D-Bus or wl-copy call is made."""
import json
import os
import shutil
import struct
import tempfile
import unittest

import helpers

phone = helpers.import_script("phone.py")
ps = helpers.import_script("privacy_settings.py")


class Codes(unittest.TestCase):
    def test_found(self):
        for text, code in (("Your verification code is 482913", "482913"),
                           ("Tu código de acceso: 123-456", "123456"),
                           ("G-552211 is your Google verification code", "552211"),
                           ("Login PIN 9921", "9921"),
                           ("Your code 2026 expires; use 7731", "7731"),
                           ("Clave de seguridad 00412345 para tu banco", "00412345")):
            self.assertEqual(phone.find_code(text), code, text)

    def test_not_a_code(self):
        for text in ("Payment of $1,500 received", "Meeting at 12:30 code review", "Order #123456 shipped",
                     "Lunch at 1300 tomorrow", "", "Your code was reviewed", "Call me at 5551234567 code"):
            self.assertIsNone(phone.find_code(text), text)


def lz4_sample():
    """'abcd' as literals, an 8-byte match 4 back (overlapping), then '!'."""
    return bytes([0x44]) + b"abcd" + b"\x04\x00" + bytes([0x10]) + b"!"


class Sessions(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)

    def test_lz4_block(self):
        self.assertEqual(phone.lz4_block(lz4_sample()), b"abcdabcdabcd!")
        with self.assertRaises(ValueError):
            phone.mozlz4(b"not mozlz4")

    def test_firefox_tabs(self):
        store = {"windows": [{"tabs": [{"index": 2, "entries": [{"title": "Old", "url": "https://old/"},
                                                                {"title": "Now", "url": "https://now/"}]},
                                       {"entries": []}]}]}
        raw = json.dumps(store).encode()
        # Literals only: a token of 15 + length bytes, then the bytes.
        n = len(raw) - 15
        lengths = b"\xff" * (n // 255) + bytes([n % 255])
        block = bytes([0xF0]) + lengths + raw
        path = os.path.join(self.dir, "recovery.jsonlz4")
        with open(path, "wb") as handle:
            handle.write(b"mozLz40\0" + struct.pack("<I", len(raw)) + block)
        self.assertEqual(phone.firefox_tabs(path), [("Now", "https://now/")])

    @staticmethod
    def snss_record(url, title):
        u = url.encode()
        t = title.encode("utf-16-le")
        body = struct.pack("<iii", 0, 7, 0) + struct.pack("<i", len(u)) + u + b"\0" * ((-len(u)) % 4)
        body += struct.pack("<i", len(title)) + t
        payload = bytes([phone.SNSS_UPDATE_NAV]) + body
        return struct.pack("<H", len(payload)) + payload

    def test_snss_navigations_and_match(self):
        data = b"SNSS" + struct.pack("<i", 3) + self.snss_record("https://a.example/", "A page") \
            + struct.pack("<H", 2) + b"\x01\x00" + self.snss_record("https://b.example/x", "A page")
        pairs = phone.snss_navigations(data)
        self.assertEqual(pairs, [("A page", "https://a.example/"), ("A page", "https://b.example/x")])
        self.assertEqual(phone.match_url("A page", pairs), "https://b.example/x")          # the newest
        self.assertIsNone(phone.match_url("Other", pairs))
        self.assertEqual(phone.snss_navigations(b"junk"), [])

    def test_page_title(self):
        self.assertEqual(phone.page_title("Acme - Dashboard - Google Chrome"), "Acme - Dashboard")
        self.assertEqual(phone.page_title("New chat - Claude — Mozilla Firefox"), "New chat - Claude")
        self.assertEqual(phone.page_title("Thing — Mozilla Firefox Private Browsing"), "Thing")

    def test_uri_paths(self):
        self.assertEqual(phone.uri_paths("file:///home/x/a%20b.jpg\r\nhttps://no\nfile:///c"),
                         ["/home/x/a b.jpg", "/c"])


class Watcher(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.calls = []
        self.saved = {k: getattr(phone, k) for k in ("PHOTOS", "ask", "copy", "xdg_open", "log")}
        self.addCleanup(lambda: [setattr(phone, k, v) for k, v in self.saved.items()])
        phone.PHOTOS = os.path.join(self.dir, "Pictures", "Phone")
        phone.ask = lambda summary, body, actions, timeout=600: self.calls.append(("ask", summary)) or "default"
        phone.copy = lambda text, sensitive=False: self.calls.append(("copy", text, sensitive))
        phone.xdg_open = lambda *argv: self.calls.append(("open",) + argv)
        phone.log = lambda text: self.calls.append(("log", text))
        self.w = phone.Watcher.__new__(phone.Watcher)       # no D-Bus

    def test_photo_moved_and_offered(self):
        src = os.path.join(self.dir, "IMG_1.jpg")
        open(src, "w").close()
        open(os.path.join(self.dir, "x"), "w").close()
        os.makedirs(phone.PHOTOS)
        open(os.path.join(phone.PHOTOS, "IMG_1.jpg"), "w").close()          # taken: a new name
        self.w.received("file://" + src)
        self.assertFalse(os.path.exists(src))
        self.assertTrue(os.path.exists(os.path.join(phone.PHOTOS, "IMG_1 (2).jpg")))
        self.assertIn(("open", "xdg-open", os.path.join(phone.PHOTOS, "IMG_1 (2).jpg")), self.calls)

    def test_other_files_left_alone(self):
        src = os.path.join(self.dir, "notes.pdf")
        open(src, "w").close()
        self.w.received("file://" + src)
        self.assertTrue(os.path.exists(src))
        self.assertEqual(self.calls, [])

    def test_link_to_clipboard(self):
        self.w.received("https://example.org/a")
        self.assertIn(("copy", "https://example.org/a", False), self.calls)
        self.assertIn(("open", "xdg-open", "https://example.org/a"), self.calls)

    def test_code_offer_is_sensitive_and_not_logged(self):
        timers = []
        old = phone.threading.Timer

        class FakeTimer:
            def __init__(self, delay, fn, args=()):
                timers.append((delay, fn, args))

            def start(self):
                pass
        phone.threading.Timer = FakeTimer
        try:
            phone.offer_code("482913", "Messages")
        finally:
            phone.threading.Timer = old
        self.assertIn(("copy", "482913", True), self.calls)
        self.assertEqual(timers[0][0], phone.CODE_CLEAR_S)
        self.assertFalse(any("482913" in c[1] for c in self.calls if c[0] == "log"))


class Hardening(unittest.TestCase):
    """The review's fixes: real-world code forms, stale and private cases."""

    def stub(self, **values):
        for key, value in values.items():
            old = getattr(phone, key)
            self.addCleanup(setattr, phone, key, old)
            setattr(phone, key, value)

    def test_codes_ending_a_sentence_or_after_a_colon(self):
        for text, code in (("PayPal: Your security code is: 849204. Your code expires in 10 minutes.", "849204"),
                           ("Your WhatsApp code: 123-456. Don't share this code", "123456"),
                           ("Your login code:7731, valid 5 min", "7731")):
            self.assertEqual(phone.find_code(text), code, text)
        for text in ("Security code balance 1234.56 due", "Login at 10:4253 code", "Your code 555-123-4567"):
            self.assertIsNone(phone.find_code(text), text)

    def test_offer_shows_the_code_masked(self):
        asked = []
        self.stub(ask=lambda summary, body, actions, timeout=600: asked.append(body) or "",
                  log=lambda text: None)
        phone.offer_code("482913", "Messages")
        self.assertNotIn("482913", asked[0])
        self.assertTrue(asked[0].startswith("••••13"))

    def test_silent_notifications_not_offered(self):
        offered = []
        self.stub(offer_code=lambda code, app: offered.append(code))
        w = phone.Watcher.__new__(phone.Watcher)
        w.offered, w.lock = {}, phone.threading.Lock()
        w.props = lambda path: {"title": "Messages", "text": "Your code is 482913", "silent": True}
        w.check_code("/x/1")
        self.assertEqual(offered, [])
        w.props = lambda path: {"title": "Messages", "text": "Your code is 482913", "silent": False}
        w.check_code("/x/2")
        self.assertEqual(offered, ["482913"])

    def test_private_window_does_not_fall_back_to_the_clipboard(self):
        said = []
        self.stub(tab_url=lambda: (None, phone.PRIVATE_WHY), clipboard_text=lambda: "https://example.org/",
                  clipboard_secret=lambda: False, notify=lambda *a: said.append(a),
                  need_phone=lambda: self.fail("nothing may be sent"))
        self.assertEqual(phone.open_on_phone(), 1)
        self.assertIn(phone.PRIVATE_WHY, said[0])

    def test_secret_clipboard_never_the_fallback(self):
        self.stub(tab_url=lambda: (None, "no match"), clipboard_text=lambda: "https://example.org/",
                  clipboard_secret=lambda: True, notify=lambda *a: None,
                  need_phone=lambda: self.fail("nothing may be sent"))
        self.assertEqual(phone.open_on_phone(), 1)

    def test_file_urls_not_matched(self):
        self.assertIsNone(phone.match_url("Notes", [("Notes", "file:///home/me/notes.html")]))
        self.assertEqual(phone.match_url("Notes", [("Notes", "https://a.example/")]), "https://a.example/")

    def test_codes_on_does_not_grow_sys_path(self):
        phone.codes_on()
        n = len(phone.sys.path)
        for _ in range(5):
            phone.codes_on()
        self.assertEqual(len(phone.sys.path), n)


class PrivacySwitch(unittest.TestCase):
    def test_off_as_shipped(self):
        self.assertFalse(ps.phone_codes_on(dict(ps.DEFAULTS)))
        self.assertTrue(ps.phone_codes_on(dict(ps.DEFAULTS, phone_codes="on")))


if __name__ == "__main__":
    unittest.main()
