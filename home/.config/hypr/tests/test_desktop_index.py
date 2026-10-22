"""desktop-index.py (Ask your desktop's search index): the cutting into
pieces, what is never indexed, BM25's order, the incremental updates and the
privacy switches; and ask-desktop.py offering search_meaning only when they
allow it. Scratch folders and scratch databases only: LM Studio is never
asked (embed / embedding_model are stubbed), privacy.conf is never read
(privacy_settings.load is stubbed)."""
import array
import math
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from helpers import SCRATCH, import_script

di = import_script("desktop-index.py")

ON = dict(di.privacy_settings.DEFAULTS)


def conf(**changes):
    c = dict(ON)
    c.update(changes)
    return c


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        handle.write(text)


def fake_embed(model, texts, timeout=0):
    """A stand-in model: one number per topic word, so "meaning" is
    predictable."""
    out = []
    for t in texts:
        low = t.lower()
        v = [float(low.count(w)) for w in ("invoice", "recipe", "kernel")] + [0.01] * (di.DIM - 3)
        n = math.sqrt(sum(x * x for x in v))
        out.append(array.array("f", [x / n for x in v]))
    return out


class Chunks(unittest.TestCase):
    def test_short_text_is_one_piece_with_its_spaces_squeezed(self):
        self.assertEqual(di.chunks("hello   there\n\n world"), ["hello there world"])
        self.assertEqual(di.chunks("   \n "), [])

    def test_long_text_is_cut_at_spaces_with_overlap(self):
        words = [f"w{i:04d}" for i in range(1000)]
        pieces = di.chunks(" ".join(words))
        self.assertGreater(len(pieces), 5)
        for p in pieces:
            self.assertLessEqual(len(p), di.CHUNK)
            for w in p.split():
                self.assertRegex(w, r"^w\d{4}$")         # never cut inside a word
        for a, b in zip(pieces, pieces[1:]):
            self.assertIn(b.split()[0], a.split())       # the next piece starts inside this one
        seen = {w for p in pieces for w in p.split()}
        self.assertEqual(seen, set(words))               # nothing lost

    def test_text_with_no_spaces_still_ends(self):
        pieces = di.chunks("x" * 2000)
        self.assertTrue(all(len(p) <= di.CHUNK for p in pieces))
        self.assertEqual(pieces[-1][-1], "x")


class Exclusions(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(dir=SCRATCH)

    def path(self, rel):
        return os.path.join(self.home, rel)

    def test_private_and_secret_names_are_never_indexed(self):
        for rel in (".ssh/notes.txt", ".gnupg/x.txt", ".local/share/keyrings/a.txt",
                    ".mozilla/firefox/p/x.json", "Documents/.hidden/a.md", "Documents/.env",
                    "Documents/prod.env", "Documents/my-secret-plan.txt", "Projects/x/aws_credentials.json",
                    "Downloads/id_rsa", "Downloads/id_rsa.pub", "Downloads/id_ed25519",
                    "Downloads/server.pem", "Downloads/passwords.txt",
                    "Projects/x/node_modules/lib/index.js", "Projects/x/app.min.js",
                    "Projects/x/package-lock.json", "Documents/photo.png"):
            self.assertIsNotNone(di.excluded(self.path(rel), self.home), rel)

    def test_ordinary_documents_are_indexed(self):
        for rel in ("Documents/notes.md", "Downloads/Invoice 2026.pdf", "Projects/site/js/app.js",
                    "Desktop/todo.txt", "Documents/data.CSV"):
            self.assertIsNone(di.excluded(self.path(rel), self.home), rel)

    def test_a_link_into_a_private_folder_is_not_followed(self):
        write(self.path(".ssh/config.txt"), "Host example")
        os.makedirs(self.path("Documents"))
        os.symlink(self.path(".ssh/config.txt"), self.path("Documents/ssh.txt"))
        self.assertEqual(di.excluded(self.path("Documents/ssh.txt"), self.home), "private folder")

    def test_content_checks(self):
        write(self.path("Documents/key.txt"), "-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n")
        self.assertEqual(di.read_text(self.path("Documents/key.txt")), (None, "has a private key"))
        with open(self.path("Documents/blob.txt"), "wb") as handle:
            handle.write(b"abc\0def" * 10)
        self.assertEqual(di.read_text(self.path("Documents/blob.txt"))[1], "binary")
        write(self.path("Documents/bundle.js"), "var a=1;" * 600)
        self.assertEqual(di.read_text(self.path("Documents/bundle.js"))[1], "minified")
        write(self.path("Documents/page.html"),
              "<html><script>var hidden=1</script><p>Hello &amp; welcome to the page</p></html>")
        text, why = di.read_text(self.path("Documents/page.html"))
        self.assertIsNone(why)
        self.assertIn("Hello & welcome", text)
        self.assertNotIn("hidden", text)

    @unittest.skipUnless(shutil.which("git"), "no git")
    def test_candidates_respect_gitignore_and_size(self):
        write(self.path("Documents/a.md"), "alpha beta gamma delta epsilon")
        write(self.path("Documents/big.txt"), "x " * (di.MAX_BYTES // 2 + 10))
        repo = self.path("Projects/proj")
        write(os.path.join(repo, "README.md"), "the project readme text here")
        write(os.path.join(repo, ".gitignore"), "build/\n")
        write(os.path.join(repo, "build/out.js"), "generated output code here")
        write(os.path.join(repo, ".github/ci.md"), "hidden workflow text here")
        subprocess.run(["git", "init", "-q", repo], check=True)
        found = di.candidates(self.home)
        self.assertIn(self.path("Documents/a.md"), found)
        self.assertIn(os.path.join(repo, "README.md"), found)
        self.assertNotIn(os.path.join(repo, "build/out.js"), found)
        self.assertNotIn(os.path.join(repo, ".github/ci.md"), found)
        self.assertNotIn(self.path("Documents/big.txt"), found)


class Bm25(unittest.TestCase):
    def setUp(self):
        self.con = di.connect(os.path.join(tempfile.mkdtemp(dir=SCRATCH), "i.sqlite3"))

    def test_more_and_rarer_matches_rank_higher(self):
        di.add_file(self.con, "/a", 1, 1, ["invoice from the plumber, invoice number 7, invoice total"])
        di.add_file(self.con, "/b", 1, 1, ["one invoice mentioned once among many other ordinary words here"])
        di.add_file(self.con, "/c", 1, 1, ["a recipe for bread with flour water salt"])
        ranked = di.bm25(self.con, "invoice")
        paths = [self.con.execute("select path from chunks where id=?", (c,)).fetchone()[0] for c, _ in ranked]
        self.assertEqual(paths, ["/a", "/b"])
        top = di.bm25(self.con, "bread invoice")[0][0]
        self.assertEqual(self.con.execute("select path from chunks where id=?", (top,)).fetchone()[0], "/c")
        self.assertEqual(di.bm25(self.con, "the and of"), [])      # stop words only

    def test_dropping_a_file_drops_its_words(self):
        di.add_file(self.con, "/a", 1, 1, ["unique zebra words"])
        di.drop_file(self.con, "/a")
        self.assertEqual(self.con.execute("select count(*) from postings").fetchone()[0], 0)
        self.assertEqual(di.bm25(self.con, "zebra"), [])


class Incremental(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(dir=SCRATCH)
        self.con = di.connect(os.path.join(self.home, "i.sqlite3"))
        write(os.path.join(self.home, "Documents/bills.txt"), "the invoice from the electricity company " * 5)
        write(os.path.join(self.home, "Documents/food.md"), "my favourite bread recipe with flour " * 5)
        write(os.path.join(self.home, "Desktop/os.txt"), "notes about the linux kernel scheduler " * 5)
        self.load = mock.patch.object(di.privacy_settings, "load", return_value=conf()).start()
        self.addCleanup(mock.patch.stopall)

    def build(self, model=None):
        lines = []
        with mock.patch.object(di, "embedding_model", return_value=model), \
                mock.patch.object(di, "server_models", return_value=None), \
                mock.patch.object(di, "embed", side_effect=fake_embed):
            di.build(home=self.home, con=self.con, log=lines.append, model=model)
        return lines[0]

    def test_only_changed_files_are_read_again(self):
        self.assertIn("3 new or changed, 0 gone", self.build())
        self.assertIn("0 new or changed, 0 gone", self.build())
        write(os.path.join(self.home, "Documents/food.md"), "a different recipe for soup with leeks " * 3)
        self.assertIn("1 new or changed, 0 gone", self.build())
        os.unlink(os.path.join(self.home, "Desktop/os.txt"))
        self.assertIn("0 new or changed, 1 gone", self.build())
        paths = {p for (p,) in self.con.execute("select distinct path from chunks")}
        self.assertEqual({os.path.basename(p) for p in paths}, {"bills.txt", "food.md"})
        self.assertEqual(di.bm25(self.con, "kernel"), [])

    def test_embeddings_are_added_later_and_used(self):
        self.build(model=None)                                 # no model: words only
        self.assertEqual(self.con.execute("select count(vec) from chunks").fetchone()[0], 0)
        self.build(model="fake-embed")                         # nothing changed, the pending pieces embedded
        n, with_vec = self.con.execute("select count(*), count(vec) from chunks").fetchone()
        self.assertEqual(n, with_vec)
        res = di.search("an invoice", 3, con=self.con, use_model=False)
        self.assertEqual(res["mode"], "keywords only")
        self.assertTrue(res["results"][0]["path"].endswith("bills.txt"))
        with mock.patch.object(di, "embed", side_effect=fake_embed):
            res = di.search("an invoice", 3, con=self.con, model="fake-embed")
        self.assertEqual(res["mode"], "meaning + keywords")
        self.assertTrue(res["results"][0]["path"].endswith("bills.txt"))
        with mock.patch.object(di, "embed", side_effect=fake_embed):
            res = di.search("bills owed", 3, con=self.con, model="fake-embed")   # no word in common
        self.assertTrue(res["results"])                        # the "meaning" still finds something
        self.assertLessEqual(len(res["results"]), 3)

    def test_a_new_model_embeds_everything_again(self):
        self.build(model="model-a")
        self.con.execute("update chunks set vec=? where id=(select min(id) from chunks)", (b"old",))
        self.build(model="model-b")
        self.assertEqual(di.meta(self.con, "model"), "model-b")
        self.assertEqual(self.con.execute("select count(*) from chunks where vec=?", (b"old",)).fetchone()[0], 0)


class Privacy(unittest.TestCase):
    def test_every_switch_on_the_way_turns_it_off(self):
        self.assertTrue(di.allowed(conf()))
        self.assertFalse(di.allowed(conf(ask="off")))
        self.assertFalse(di.allowed(conf(ask_files="off")))
        self.assertFalse(di.allowed(conf(ask_index="off")))
        self.assertTrue(di.allowed(conf(ask_clipboard="off", ask_activity="off")))

    def test_build_and_search_do_nothing_when_off(self):
        home = tempfile.mkdtemp(dir=SCRATCH)
        write(os.path.join(home, "Documents/a.txt"), "some words to index here")
        db = os.path.join(home, "i.sqlite3")
        with mock.patch.object(di.privacy_settings, "load", return_value=conf(ask_index="off")):
            self.assertEqual(di.build(home=home, con=di.connect(db)), di.OFF_TEXT)
            self.assertTrue(di.search("words").get("off"))
        con = di.connect(db)
        self.assertEqual(con.execute("select count(*) from files").fetchone()[0], 0)

    def test_ask_desktop_offers_search_meaning_only_when_allowed(self):
        ask = import_script("ask-desktop.py")
        names = lambda tools: {t["function"]["name"] for t in tools}  # noqa: E731
        self.assertIn("search_meaning", names(ask.allowed_tools({"files", "index"})))
        self.assertNotIn("search_meaning", names(ask.allowed_tools({"files", "clipboard", "activity"})))
        self.assertIn("note", ask.call_search("search_meaning", {"query": "x"}, {"files"}))
        with mock.patch.object(ask.desktop_index, "allowed", return_value=True), \
                mock.patch.object(ask.os.path, "exists", return_value=False):
            self.assertFalse(ask.index_ready())                # no index yet: not offered
        with mock.patch.object(ask.desktop_index, "allowed", return_value=False):
            self.assertFalse(ask.index_ready())


if __name__ == "__main__":
    unittest.main()
