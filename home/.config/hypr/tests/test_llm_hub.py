"""llm_hub.py (the model manager's and the launcher's Hugging Face and disk
side) and llm_models.py's download bookkeeping: a repo tree's variant
sizes, the model folders on disk matched to lms ls's models, what may be
deleted and the delete itself, the download status files and what cancel()
agrees to signal. No network, no lms: a scratch models folder, the lms ls
cache stubbed."""
import json
import os
import tempfile
import time
import unittest
from unittest import mock

import helpers  # noqa: F401  (scratch XDG dirs before the imports below)

helpers.import_script("llm_models.py")
import llm_hub  # noqa: E402
import llm_models  # noqa: E402


def tree(*files):
    return [{"type": "file", "path": p, "size": s} for p, s in files]


class Variants(unittest.TestCase):
    def test_sizes_per_variant_split_parts_summed(self):
        sizes = llm_hub.variant_sizes(tree(
            ("Model-Q4_K_M.gguf", 100), ("Model-Q8_0-00001-of-00002.gguf", 150),
            ("Model-Q8_0-00002-of-00002.gguf", 50), ("mmproj-Model-BF16.gguf", 9),
            ("README.md", 1)))
        self.assertEqual(sizes, {"Q4_K_M": 100, "Q8_0": 200})

    def test_two_copies_of_one_variant_count_the_biggest(self):
        sizes = llm_hub.variant_sizes(tree(("a/Model-Q4_K_M.gguf", 100), ("b/Model-Q4_K_M.gguf", 120)))
        self.assertEqual(sizes, {"Q4_K_M": 120})

    def test_bad_tree(self):
        self.assertEqual(llm_hub.variant_sizes({"error": "x"}), {})
        self.assertEqual(llm_hub.variant_sizes([None, {"type": "directory", "path": "x"}]), {})

    def test_variants_smallest_first_default_marked(self):
        with mock.patch.object(llm_hub, "repo_tree", lambda r: tree(
                ("M-Q8_0.gguf", 8e9), ("M-Q4_K_M.gguf", 4e9), ("M-Q2_K.gguf", 2e9))), \
                mock.patch.object(llm_hub, "hardware", lambda: None):
            out = llm_hub.variants("a/b")
        self.assertEqual([v["variant"] for v in out], ["Q2_K", "Q4_K_M", "Q8_0"])
        self.assertEqual([v["best"] for v in out], [False, True, False])


class Pasted(unittest.TestCase):
    """What is copied off Hugging Face's pages: llm_hub.parse_ref."""
    def ref(self, text):
        out = llm_hub.parse_ref(text)
        return out and (out["kind"], out["repo"], out["variant"])

    def test_page_and_file_addresses(self):
        self.assertEqual(self.ref("https://huggingface.co/unsloth/Qwen3-8B-GGUF"),
                         ("model", "unsloth/Qwen3-8B-GGUF", None))
        self.assertEqual(self.ref("https://huggingface.co/unsloth/Qwen3-8B-GGUF/tree/main"),
                         ("model", "unsloth/Qwen3-8B-GGUF", None))
        self.assertEqual(self.ref("huggingface.co/unsloth/Qwen3-8B-GGUF/blob/main/Qwen3-8B-Q6_K.gguf"),
                         ("model", "unsloth/Qwen3-8B-GGUF", "Q6_K"))
        self.assertEqual(self.ref("https://huggingface.co/a/B-GGUF/resolve/main/Q8/B-Q8_0-00001-of-00002.gguf?download=true"),
                         ("model", "a/B-GGUF", "Q8_0"))

    def test_use_this_model_lines(self):
        self.assertEqual(self.ref("ollama run hf.co/bartowski/Qwen_Qwen3-8B-GGUF:Q4_K_M"),
                         ("model", "bartowski/Qwen_Qwen3-8B-GGUF", "Q4_K_M"))
        self.assertEqual(self.ref("llama-server -hf ggml-org/gemma-3-1b-it-GGUF:q8_0"),
                         ("model", "ggml-org/gemma-3-1b-it-GGUF", "Q8_0"))
        self.assertEqual(self.ref("lms get lmstudio-community/Qwen3-8B-GGUF@q4_k_m"),
                         ("model", "lmstudio-community/Qwen3-8B-GGUF", "Q4_K_M"))
        self.assertEqual(self.ref("unsloth/Qwen3-8B-GGUF:latest"), ("model", "unsloth/Qwen3-8B-GGUF", None))

    def test_not_models(self):
        self.assertEqual(self.ref("https://huggingface.co/datasets/HuggingFaceFW/fineweb"),
                         ("dataset", "HuggingFaceFW/fineweb", None))
        self.assertEqual(self.ref("https://huggingface.co/spaces/a/b")[0], "space")
        self.assertIsNone(self.ref("huggingface.co/docs/hub"))
        self.assertIsNone(self.ref("qwen coder"))
        self.assertIsNone(self.ref("llama 3/8b instruct"))      # words with a slash are still words
        self.assertIsNone(self.ref(""))

    def test_search_page(self):
        out = llm_hub.parse_ref("https://huggingface.co/models?search=gemma%203&library=gguf")
        self.assertEqual((out["kind"], out["words"]), ("search", "gemma 3"))

    def test_preferred_variant_only_when_present(self):
        repo = {"id": "a/B-GGUF", "siblings": [{"rfilename": "B-Q4_K_M.gguf"}, {"rfilename": "B-Q6_K.gguf"}]}
        self.assertEqual(llm_hub.hf_row(repo, prefer="Q6_K")["variant"], "Q6_K")
        self.assertEqual(llm_hub.hf_row(repo, prefer="Q2_K")["variant"], "Q4_K_M")


class Disk(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.dir.name, "models")
        self.make("lmstudio-community/Qwen3-8B-GGUF/Qwen3-8B-Q4_K_M.gguf", 400)
        self.make("someone/Tiny-GGUF/Tiny-Q8_0.gguf", 100)
        self.make("someone/Tiny-GGUF/Tiny-Q4_K_M.gguf", 60)
        self.make("other/Left-GGUF/mmproj-Left-BF16.gguf", 30)
        self.models = [
            llm_models.Model("qwen3-8b", "Qwen3 8B", "local", "qwen/qwen3-8b", "8B", "qwen/qwen3-8b"),
            llm_models.Model("tiny-q8", "Tiny", "local", "tiny-q8", "", "someone/Tiny-GGUF/Tiny-Q8_0.gguf"),
            llm_models.Model("tiny-q4", "Tiny", "local", "tiny-q4", "", "someone/Tiny-GGUF/Tiny-Q4_K_M.gguf"),
        ]
        patches = [mock.patch.object(llm_models, "LMS_MODELS", self.root),
                   mock.patch.object(llm_models, "local_models", lambda: list(self.models)),
                   mock.patch.object(llm_models, "refresh", lambda *a, **k: True),
                   mock.patch.object(llm_models, "downloading", lambda repo: False)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self.dir.cleanup()

    def make(self, rel, size):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(b"x" * size)

    def test_folders_matched_to_models(self):
        disk = {e["folder"]: e for e in llm_hub.on_disk()}
        self.assertEqual(set(disk), {"lmstudio-community/Qwen3-8B-GGUF", "someone/Tiny-GGUF", "other/Left-GGUF"})
        self.assertEqual([m.name for m in disk["lmstudio-community/Qwen3-8B-GGUF"]["models"]], ["qwen3-8b"])
        self.assertEqual(sorted(m.name for m in disk["someone/Tiny-GGUF"]["models"]), ["tiny-q4", "tiny-q8"])
        self.assertEqual(disk["other/Left-GGUF"]["models"], [])        # a lone mmproj
        self.assertEqual(disk["someone/Tiny-GGUF"]["size"], 160)
        self.assertEqual(llm_hub.on_disk()[0]["folder"], "lmstudio-community/Qwen3-8B-GGUF")   # biggest first

    def test_partial_download_flagged(self):
        self.make("x/Part-GGUF/downloading_Part-Q4_K_M.gguf.part", 5)
        entry = next(e for e in llm_hub.on_disk() if e["folder"] == "x/Part-GGUF")
        self.assertTrue(entry["partial"])

    def test_refusals(self):
        for bad in ("someone", "../models/someone/Tiny-GGUF", "someone/Tiny-GGUF/x", "a/..", "/etc/x", "no/such"):
            with self.assertRaises(ValueError, msg=bad):
                llm_hub.check_removable(bad)
        with self.assertRaisesRegex(ValueError, "loaded"):
            llm_hub.check_removable("someone/Tiny-GGUF", loaded={"tiny-q4"})
        with mock.patch.object(llm_models, "downloading", lambda repo: True):
            with self.assertRaisesRegex(ValueError, "downloading"):
                llm_hub.check_removable("someone/Tiny-GGUF")

    def test_symlink_out_is_refused(self):
        outside = os.path.join(self.dir.name, "elsewhere")
        os.makedirs(outside)
        os.symlink(outside, os.path.join(self.root, "someone", "Link-GGUF"))
        with self.assertRaises(ValueError):
            llm_hub.check_removable("someone/Link-GGUF")
        self.assertTrue(os.path.isdir(outside))

    def test_remove_deletes_folder_and_empty_author(self):
        freed = llm_hub.remove("other/Left-GGUF")
        self.assertEqual(freed, 30)
        self.assertFalse(os.path.exists(os.path.join(self.root, "other")))
        llm_hub.remove("someone/Tiny-GGUF")
        self.assertFalse(os.path.exists(os.path.join(self.root, "someone")))
        self.assertTrue(os.path.isdir(os.path.join(self.root, "lmstudio-community", "Qwen3-8B-GGUF")))


class Downloads(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        p = mock.patch.object(llm_models, "DL_DIR", self.dir.name)
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        self.dir.cleanup()

    def test_status_round_trip_and_forget(self):
        llm_models._write_status("a/B-GGUF", state="done", pct=100.0, variant="Q4_K_M")
        got = llm_models.downloads()
        self.assertEqual([(d["repo"], d["state"], d["variant"]) for d in got], [("a/B-GGUF", "done", "Q4_K_M")])
        llm_models.forget_download("a/B-GGUF")
        self.assertEqual(llm_models.downloads(), [])

    def test_running_without_its_lock_is_failed(self):
        llm_models._write_status("a/B-GGUF", state="running", pct=40.0)
        self.assertEqual(llm_models.downloads()[0]["state"], "failed")

    def test_old_ended_ones_drop_off(self):
        llm_models._write_status("a/B-GGUF", state="done")
        path = llm_models._status_path("a/B-GGUF")
        with open(path) as handle:
            data = json.load(handle)
        data["time"] = time.time() - llm_models.DL_KEEP - 5
        with open(path, "w") as handle:
            json.dump(data, handle)
        self.assertEqual(llm_models.downloads(), [])

    def test_cancel_signals_only_a_get_of_that_repo(self):
        llm_models._write_status("a/B-GGUF", state="running", pid=os.getpid())
        with mock.patch.object(os, "kill") as kill:
            self.assertFalse(llm_models.cancel("a/B-GGUF"))        # this test runner is no `get`
            kill.assert_not_called()
            self.assertFalse(llm_models.cancel("no/such"))


if __name__ == "__main__":
    unittest.main()
