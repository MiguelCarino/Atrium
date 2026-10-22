"""screen-ask.py: tables to CSV, what a capture may show, which model
answers (never a cloud one, never by unloading another) and the request it
sends. No screen, no LM Studio: every outside call is stubbed."""
import base64
import os
import tempfile
import unittest
from unittest import mock

from helpers import import_script

sa = import_script("screen-ask.py")

ROWS = [{"id": "google/gemma-4-e4b", "type": "vlm", "state": "not-loaded"},
        {"id": "qwen/qwen3.8-27b", "type": "vlm", "state": "loaded"},
        {"id": "glm-4.7-flash", "type": "llm", "state": "not-loaded"},
        {"id": "nomic-embed", "type": "embeddings", "state": "not-loaded"}]
SIZES = {"google/gemma-4-e4b": 6e9, "qwen/qwen3.8-27b": 18e9, "glm-4.7-flash": 21e9}


class Tables(unittest.TestCase):
    def test_csv_block(self):
        answer = "Sure:\n```csv\nName,Qty\nApple,3\n```\n"
        self.assertEqual(sa.to_csv(answer), "Name,Qty\nApple,3\n")

    def test_markdown_table(self):
        answer = ("Here:\n\n| Name | Qty | Note |\n|---|:---:|---|\n| Apple | 3 | red, sweet |\n"
                  "| Pear | 5 | |\n\nDone.")
        self.assertEqual(sa.to_csv(answer), 'Name,Qty,Note\nApple,3,"red, sweet"\nPear,5,\n')

    def test_tabs_and_commas(self):
        self.assertEqual(sa.to_csv("a\tb\n1\t2"), "a,b\n1,2\n")
        self.assertEqual(sa.to_csv("a,b\n1,2"), "a,b\n1,2\n")

    def test_no_table(self):
        for answer in ("It is an error, of sorts.", "One line | only", "a,b\n1,2,3", ""):
            with self.subTest(answer=answer):
                self.assertIsNone(sa.to_csv(answer))


class Capture(unittest.TestCase):
    clients = [{"class": "kitty", "title": "~", "workspace": {"id": 1}, "at": [0, 0], "size": [800, 600]},
               {"class": "org.keepassxc.KeePassXC", "title": "db", "workspace": {"id": 1},
                "at": [1000, 0], "size": [500, 500]},
               {"class": "KeePassXC", "title": "db", "workspace": {"id": 4}, "at": [0, 0], "size": [900, 900]}]

    def is_private(self, c):
        return "keepass" in c["class"].lower()

    def test_geometry(self):
        self.assertEqual(sa.parse_geometry("10,20 300x400"), (10, 20, 300, 400))
        self.assertEqual(sa.parse_geometry("-1920,0 10x10"), (-1920, 0, 10, 10))
        self.assertIsNone(sa.parse_geometry(""))
        self.assertIsNone(sa.parse_geometry("selection cancelled"))

    def test_private_in(self):
        shown = sa.visible_workspaces([{"activeWorkspace": {"id": 1}, "specialWorkspace": {"id": 0}}])
        self.assertEqual(shown, {1})
        self.assertEqual(sa.private_in(self.clients, (0, 0, 500, 500), shown, self.is_private), [])
        self.assertEqual(sa.private_in(self.clients, (900, 100, 200, 200), shown, self.is_private),
                         ["org.keepassxc.KeePassXC"])
        self.assertEqual(len(sa.private_in(self.clients, None, shown, self.is_private)), 1)
        self.assertEqual(sa.private_in(self.clients, None, {2}, self.is_private), [])   # hidden: fine

    def test_window_refused_when_private(self):
        win = {"class": "Bitwarden", "title": "Vault", "at": [0, 0], "size": [10, 10]}
        with mock.patch.object(sa, "hyprctl_json", side_effect=lambda *a: win if a == ("activewindow",) else []), \
                mock.patch.object(sa.subprocess, "run") as run:
            png, why = sa.capture("window")
        self.assertIsNone(png)
        self.assertIn("private", why)
        run.assert_not_called()                     # grim never ran


class Models(unittest.TestCase):
    def test_candidates_order(self):
        got = sa.candidates(ROWS, ["google/gemma-4-e4b"], SIZES)
        self.assertEqual(got, [("qwen/qwen3.8-27b", True), ("google/gemma-4-e4b", False)])
        got = sa.candidates(ROWS, [], SIZES, need_vision=False)
        self.assertEqual([k for k, _ in got], ["qwen/qwen3.8-27b", "google/gemma-4-e4b", "glm-4.7-flash"])

    def stubs(self, rows, fit=None, ensure=(True, "")):
        return [mock.patch.object(sa.llm_models, "_gamemode_on", return_value=False),
                mock.patch.object(sa, "server_rows", return_value=rows),
                mock.patch.object(sa, "_prefer", return_value=["google/gemma-4-e4b"]),
                mock.patch.object(sa, "_sizes", return_value=SIZES),
                mock.patch.object(sa, "_fit", side_effect=lambda m: (fit or {}).get(m.ident)),
                mock.patch.object(sa.llm_models, "ensure_local", return_value=ensure)]

    def pick(self, rows, **kw):
        patches = self.stubs(rows, **kw)
        for p in patches:
            p.start()
        try:
            return sa.pick_model(), sa.llm_models.ensure_local
        finally:
            for p in patches:
                p.stop()

    def test_loaded_wins_without_loading(self):
        (key, why), ensure = self.pick(ROWS)
        self.assertEqual(key, "qwen/qwen3.8-27b")
        ensure.assert_not_called()

    def test_loads_the_one_that_fits(self):
        rows = [dict(r, state="not-loaded") for r in ROWS]
        (key, why), ensure = self.pick(rows, fit={"google/gemma-4-e4b": {"verdict": "fits"}})
        self.assertEqual(key, "google/gemma-4-e4b")
        ensure.assert_called_once()

    def test_none_fits_says_why_and_loads_nothing(self):
        rows = [dict(r, state="not-loaded") for r in ROWS] + [{"id": "big", "type": "llm", "state": "loaded"}]
        wont = {"verdict": "won't fit"}
        (key, why), ensure = self.pick(rows, fit={"google/gemma-4-e4b": wont, "qwen/qwen3.8-27b": wont})
        self.assertIsNone(key)
        self.assertIn("nothing was unloaded", why)
        self.assertIn("big", why)
        ensure.assert_not_called()

    def test_no_vision_model(self):
        (key, why), _ = self.pick([{"id": "glm", "type": "llm", "state": "loaded"}])
        self.assertIsNone(key)
        self.assertIn("pictures", why)

    def test_gamemode_refuses(self):
        with mock.patch.object(sa.llm_models, "_gamemode_on", return_value=True), \
                mock.patch.object(sa, "server_rows") as rows:
            key, why = sa.pick_model()
        self.assertIsNone(key)
        self.assertIn("gamemode", why)
        rows.assert_not_called()


class Request(unittest.TestCase):
    def test_image_message_and_ask(self):
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
        fd, path = tempfile.mkstemp(suffix=".png")
        with os.fdopen(fd, "wb") as handle:
            handle.write(png)
        self.addCleanup(os.remove, path)
        msg = sa.first_message("what is this", path)
        self.assertEqual(msg["content"][0], {"type": "text", "text": "what is this"})
        self.assertTrue(msg["content"][1]["image_url"]["url"].startswith("data:image/png;base64,"))
        with mock.patch.object(sa.worker(), "ask", return_value="a dot") as ask:
            self.assertEqual(sa.ask("google/gemma-4-e4b", [msg]), "a dot")
        model, _prompt, _system = ask.call_args[0]
        extra = ask.call_args[1]["extra"]
        self.assertEqual(model.ident, "google/gemma-4-e4b")
        self.assertTrue(model.local)
        self.assertEqual(extra["messages"][0]["role"], "system")
        self.assertEqual(extra["messages"][1], msg)

    def test_text_message_is_clipped(self):
        msg = sa.first_message("explain", text="x" * (sa.TEXT_CHARS + 50))
        self.assertLessEqual(len(msg["content"]), sa.TEXT_CHARS + 20)


if __name__ == "__main__":
    unittest.main()


class ReviewFixes(unittest.TestCase):
    """--delete only removes our own screenshots; an OCR failure is said, not
    a traceback, and the picture is still deleted."""

    def test_owned(self):
        self.assertTrue(sa.owned(os.path.join(sa.RUNTIME, "screen-ask-x.png")))
        self.assertFalse(sa.owned(os.path.join(sa.RUNTIME, "other.png")))
        self.assertFalse(sa.owned(os.path.expanduser("~/Pictures/screen-ask-x.png")))
        self.assertFalse(sa.owned(""))

    def test_ocr_error_is_reported_and_file_removed(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(sa, "RUNTIME", tmp):
            png = os.path.join(tmp, "screen-ask-1.png")
            open(png, "wb").close()
            with mock.patch.object(sa, "ocr_text", side_effect=OSError("down")), \
                    mock.patch.object(sa, "notify") as notify:
                sa.ocr_command(png, delete=True)
            self.assertFalse(os.path.exists(png))
            self.assertIn("down", notify.call_args[0][1])

    def test_delete_refuses_foreign_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            other = os.path.join(tmp, "keep.png")
            open(other, "wb").close()
            with mock.patch.object(sa, "ocr_text", return_value=("", "tesseract")), \
                    mock.patch.object(sa, "notify"):
                sa.ocr_command(other, delete=True)
            self.assertTrue(os.path.exists(other))

    def test_gamemode_still_deletes_handed_over_picture(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(sa, "RUNTIME", tmp):
            png = os.path.join(tmp, "screen-ask-2.png")
            open(png, "wb").close()
            with mock.patch.object(sa.llm_models, "_gamemode_on", return_value=True), \
                    mock.patch.object(sa, "notify"), mock.patch.object(sa.signal, "signal"):
                sa.main(["image", png, "--delete"])
            self.assertFalse(os.path.exists(png))
