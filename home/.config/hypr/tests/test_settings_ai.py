"""llm-gpu.py and llm_models.py's settings (Settings > AI & models): the fit
calculator, the GGUF header reader, nvidia-smi's CSV, the gamemode hook
against a stubbed lms, llm.json's roles / context / slots and the quick
answer's fallback. Scratch files only: no lms, no nvidia-smi, no hyprctl."""
import json
import os
import struct
import tempfile
import unittest
from unittest import mock

import helpers

gpu = helpers.import_script("llm-gpu.py")
llm_models = gpu.llm_models

GB = 1e9

# Headers as gguf_meta() keeps them, from the three models on this machine.
GEMMA = {"general.architecture": "gemma4", "gemma4.block_count": 42, "gemma4.embedding_length": 2560,
         "gemma4.attention.head_count": 8, "gemma4.attention.head_count_kv": 2,
         "gemma4.attention.key_length": 512, "gemma4.attention.value_length": 512,
         "gemma4.attention.sliding_window": 512, "gemma4.attention.shared_kv_layers": 18,
         "gemma4.attention.sliding_window_pattern": ([True] * 5 + [False]) * 7,
         "gemma4.attention.key_length_swa": 256, "gemma4.attention.value_length_swa": 256}
QWEN = {"general.architecture": "qwen35", "qwen35.block_count": 65, "qwen35.embedding_length": 5120,
        "qwen35.attention.head_count": 24, "qwen35.attention.head_count_kv": 4,
        "qwen35.attention.key_length": 256, "qwen35.attention.value_length": 256,
        "qwen35.full_attention_interval": 4, "qwen35.ssm.inner_size": 6144, "qwen35.ssm.state_size": 128}
GLM = {"general.architecture": "deepseek2", "deepseek2.block_count": 47, "deepseek2.embedding_length": 2048,
       "deepseek2.attention.head_count": 20, "deepseek2.attention.head_count_kv": 1,
       "deepseek2.attention.key_length": 576, "deepseek2.attention.value_length": 512,
       "deepseek2.attention.kv_lora_rank": 512}
LLAMA = {"general.architecture": "llama", "llama.block_count": 32, "llama.embedding_length": 4096,
         "llama.attention.head_count": 32, "llama.attention.head_count_kv": 8}


class KvCache(unittest.TestCase):
    def test_plain_gqa(self):
        # 32 layers x 8 heads x (128 + 128) x 2 bytes = 128 KiB a token.
        self.assertEqual(gpu.kv_bytes(LLAMA, 1000), 32 * 8 * 256 * 2 * 1000)

    def test_hybrid_counts_every_nth_layer_and_the_recurrent_state(self):
        attn = 16 * 4 * 512 * 2 * 32768             # layers 4, 8, ... 64
        state = 49 * 6144 * 128 * 4                 # the other 49, per slot
        self.assertEqual(gpu.kv_bytes(QWEN, 32768, 1), attn + state)
        self.assertEqual(gpu.kv_bytes(QWEN, 32768, 4), attn + 4 * state)

    def test_sliding_window_and_shared_layers(self):
        # 24 layers of their own: 4 full, 20 sliding (window x slots + ubatch).
        full = 4 * 2 * 1024 * 2 * 32768
        swa = 20 * 2 * 512 * 2 * (512 * 4 + 512)
        self.assertEqual(gpu.kv_bytes(GEMMA, 32768, 4), full + swa)
        # A context shorter than the window keeps only the context.
        self.assertEqual(gpu.kv_bytes(GEMMA, 256, 1), 4 * 2 * 1024 * 2 * 256 + 20 * 2 * 512 * 2 * 256)

    def test_mla_counted_from_its_recorded_sizes(self):
        self.assertEqual(gpu.kv_bytes(GLM, 32768), 47 * 1 * (576 + 512) * 2 * 32768)

    def test_per_layer_head_counts(self):
        meta = dict(LLAMA, **{"llama.attention.head_count_kv": [8, 0] * 16})
        self.assertEqual(gpu.kv_bytes(meta, 10), 16 * 8 * 256 * 2 * 10)

    def test_not_enough_to_go_on(self):
        self.assertIsNone(gpu.kv_bytes(None, 1000))
        self.assertIsNone(gpu.kv_bytes({"general.architecture": "x"}, 1000))


class RuleOfThumb(unittest.TestCase):
    def test_params(self):
        self.assertEqual(gpu.params_billions("27B"), 27)
        self.assertEqual(gpu.params_billions("7.5B"), 7.5)
        self.assertAlmostEqual(gpu.params_billions("270M"), 0.27)
        # A mixture of experts: from the file, Q5 counted as 5.5 bits.
        self.assertAlmostEqual(gpu.params_billions("64x2.6B", 22e9, "Q5_K_M"), 22e9 * 8 / 5.5 / 1e9)
        self.assertIsNone(gpu.params_billions("", 0, ""))

    def test_estimate_prefers_the_header(self):
        row = {"paramsString": "8B", "sizeBytes": 5e9}
        self.assertEqual(gpu.estimate(row, 1000, 1, LLAMA), (32 * 8 * 256 * 2 * 1000, "gguf"))
        self.assertEqual(gpu.estimate(row, 1000, 1, None), (8 * gpu.KV_PER_B * 1000, "rule of thumb"))
        self.assertEqual(gpu.estimate({}, 1000, 1, None), (0, ""))


class Fit(unittest.TestCase):
    TOTAL = 24 * GB

    def test_verdicts(self):
        # room = 24 - 2 = 22; need = size + kv + 0.5
        self.assertEqual(gpu.fit(10 * GB, 1 * GB, self.TOTAL)["verdict"], "fits")
        self.assertEqual(gpu.fit(20 * GB, 1.0 * GB, self.TOTAL)["verdict"], "tight")      # 0.5 spare
        self.assertEqual(gpu.fit(20 * GB, 0.5 * GB, self.TOTAL)["verdict"], "fits")       # 1.0 spare
        over = gpu.fit(21 * GB, 1.0 * GB, self.TOTAL)
        self.assertEqual(over["verdict"], "won't fit")
        self.assertEqual(over["text"], "won't fit (would spill to RAM: slow)")
        self.assertEqual(over["spare"], -0.5 * GB)

    def test_next_to_what_is_loaded(self):
        self.assertEqual(gpu.fit(6.3 * GB, 0.6 * GB, self.TOTAL, others=21 * GB)["verdict"], "won't fit")
        self.assertEqual(gpu.fit(6.3 * GB, 0.6 * GB, self.TOTAL, others=2 * GB)["verdict"], "fits")

    def test_slots(self):
        self.assertEqual(gpu.per_slot(32768, 4), 8192)
        self.assertEqual(gpu.per_slot(32768, None), 32768 // gpu.LMS_DEFAULT_PARALLEL)
        self.assertIn("8k", gpu.slot_warning(32768, 4))
        self.assertEqual(gpu.slot_warning(32768, 1), "")
        self.assertEqual(gpu.slot_warning(49152, 2), "")

    def test_ttl(self):
        self.assertEqual(gpu.ttl_left({"ttlMs": 1800000, "lastUsedTime": 1000000}, 1000000 + 600000), 1200)
        self.assertEqual(gpu.ttl_left({"ttlMs": 1000, "lastUsedTime": 5}, 10 ** 9), 0)
        self.assertIsNone(gpu.ttl_left({}, 0))


class Smi(unittest.TestCase):
    def test_parse(self):
        card = gpu.parse_smi("NVIDIA GeForce RTX 4090, 21343, 24564\n",
                             "770962, cosmic-term, 55\n1490157, /x/llama-server, 19084\nbad\n")
        self.assertEqual(card["name"], "NVIDIA GeForce RTX 4090")
        self.assertEqual(card["total"], 24564 * 2 ** 20)
        self.assertEqual([p["name"] for p in card["procs"]], ["llama-server", "cosmic-term"])
        self.assertEqual(card["procs"][0]["used"], 19084 * 2 ** 20)

    def test_no_card(self):
        self.assertIsNone(gpu.parse_smi("", ""))
        self.assertIsNone(gpu.parse_smi("garbage", ""))


def gguf_file(path, kvs, tensors=(), data=0):
    """A tiny GGUF: the header, the metadata and a tensor table of (name,
    offset) -- each one-dimensional, type 0 -- followed by `data` bytes."""
    def s(text):
        raw = text.encode()
        return struct.pack("<Q", len(raw)) + raw
    out = b"GGUF" + struct.pack("<IQQ", 3, len(tensors), len(kvs))
    for key, kind, value in kvs:
        out += s(key) + struct.pack("<I", kind)
        if kind == 8:
            out += s(value)
        elif kind == 9:
            item, items = value
            out += struct.pack("<IQ", item, len(items))
            out += b"".join(s(v) for v in items) if item == 8 else \
                struct.pack(f"<{len(items)}{gpu._SCALAR[item]}", *items)
        else:
            out += struct.pack("<" + gpu._SCALAR[kind], value)
    for name, offset in tensors:
        out += s(name) + struct.pack("<IQ", 1, 4) + struct.pack("<IQ", 0, offset)
    out += b"\0" * ((-len(out)) % 32) + b"\0" * data
    with open(path, "wb") as handle:
        handle.write(out)


class Gguf(unittest.TestCase):
    def test_reads_what_the_cache_needs(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "m.gguf")
            gguf_file(path, [("general.architecture", 8, "llama"),
                             ("tokenizer.ggml.tokens", 9, (8, ["a", "bb", "ccc"])),
                             ("llama.block_count", 4, 32),
                             ("llama.attention.head_count_kv", 4, 8),
                             ("llama.attention.sliding_window_pattern", 9, (7, [True, False])),
                             ("tokenizer.ggml.scores", 9, (6, [0.5, 0.25])),
                             ("llama.rope.freq_base", 6, 10000.0)])
            meta = gpu.gguf_meta(path)
        self.assertEqual(meta, {"general.architecture": "llama", "llama.block_count": 32,
                                "llama.attention.head_count_kv": 8,
                                "llama.attention.sliding_window_pattern": [True, False], "_host_bytes": 0})

    def test_counts_the_tensors_kept_in_ram(self):
        # Gemma 4's per-layer token embeddings stay in RAM: their bytes, from
        # the offsets (the last tensor runs to the end of the file).
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "m.gguf")
            gguf_file(path, [("general.architecture", 8, "gemma4")],
                      [("token_embd.weight", 0), ("per_layer_token_embd.weight", 1000),
                       ("blk.0.ffn_down.weight", 3000), ("per_layer_token_embd.extra", 3500)], data=4000)
            self.assertEqual(gpu.gguf_meta(path)["_host_bytes"], 2000 + 500)
        self.assertEqual(gpu.card_size({"sizeBytes": 6.3 * GB}, {"_host_bytes": 2.3 * GB}), 4.0 * GB)
        self.assertEqual(gpu.card_size({"sizeBytes": 17 * GB}, None), 17 * GB)

    def test_not_a_gguf(self):
        with tempfile.NamedTemporaryFile(suffix=".gguf") as f:
            f.write(b"nope" * 10)
            f.flush()
            self.assertIsNone(gpu.gguf_meta(f.name))

    def test_model_file(self):
        with tempfile.TemporaryDirectory() as root:
            repo = os.path.join(root, "lmstudio-community", "Qwen3.8-27B-GGUF")
            os.makedirs(repo)
            for name in ("mmproj-Qwen3.8-27B-BF16.gguf", "Qwen3.8-27B-Q4_K_M.gguf"):
                open(os.path.join(repo, name), "w").close()
            self.assertEqual(gpu.model_file("qwen/qwen3.8-27b", root),
                             os.path.join(repo, "Qwen3.8-27B-Q4_K_M.gguf"))
            self.assertEqual(gpu.model_file("lmstudio-community/Qwen3.8-27B-GGUF/Qwen3.8-27B-Q4_K_M.gguf", root),
                             os.path.join(repo, "Qwen3.8-27B-Q4_K_M.gguf"))
            self.assertIsNone(gpu.model_file("qwen/qwen3.6-27b", root))      # deleted
            self.assertIsNone(gpu.model_file("", root))


class Conf(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "llm-gpu.conf")

    def tearDown(self):
        self.dir.cleanup()

    def test_defaults_and_writes(self):
        self.assertEqual(gpu.read_conf(self.path), {"unload_for_games": "on", "reload_after_games": "off"})
        gpu.write_conf("reload_after_games", "on", self.path)
        self.assertEqual(gpu.read_conf(self.path)["reload_after_games"], "on")
        with open(self.path, "a") as handle:
            handle.write("unload_for_games=maybe\nstray line\n")
        self.assertEqual(gpu.read_conf(self.path)["unload_for_games"], "on")
        with self.assertRaises(ValueError):
            gpu.write_conf("nope", "on", self.path)
        with self.assertRaises(ValueError):
            gpu.write_conf("unload_for_games", "yes", self.path)


class Gamemode(unittest.TestCase):
    """The hook with lms stubbed: what it would run, and the list it keeps."""

    LOADED = [{"modelKey": "glm-4.7-flash-x", "identifier": "glm-4.7-flash-x", "contextLength": 32768,
               "parallel": 4, "ttlMs": 1800000}]

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.calls = []
        self.loads = []
        patches = [mock.patch.object(gpu, "CONF", os.path.join(self.dir.name, "llm-gpu.conf")),
                   mock.patch.object(gpu, "UNLOADED", os.path.join(self.dir.name, "unloaded.json")),
                   mock.patch.object(gpu, "LOCK", os.path.join(self.dir.name, "lock")),
                   mock.patch.object(gpu, "_lms", lambda *a, **k: self.calls.append(a)),
                   mock.patch.object(gpu, "lms_ps", lambda: list(self.LOADED)),
                   mock.patch.object(gpu.llm_models, "resolve",
                                     lambda w, *a, **k: llm_models.Model("glm", "GLM", "local", w)),
                   mock.patch.object(gpu.llm_models, "ensure_local",
                                     lambda m, *a: (self.loads.append(m.ident), (True, ""))[1])]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.dir.cleanup)

    def test_not_running_is_a_no_op(self):
        with mock.patch.object(gpu, "running", lambda: False):
            self.assertEqual(gpu.gamemode("on"), "LM Studio is not running")
        self.assertEqual(self.calls, [])
        self.assertIsNone(gpu.read_unloaded())

    def test_on_unloads_and_remembers_off_keeps_the_list(self):
        with mock.patch.object(gpu, "running", lambda: True):
            gpu.gamemode("on")
        self.assertEqual(self.calls, [("unload", "--all")])
        left = gpu.read_unloaded()
        self.assertEqual([m["modelKey"] for m in left["models"]], ["glm-4.7-flash-x"])
        self.assertIsNone(left["game_over"])
        gpu.gamemode("off")
        self.assertEqual(self.loads, [])                    # reload_after_games is off
        self.assertIsNotNone(gpu.read_unloaded()["game_over"])

    def test_off_reloads_when_asked(self):
        gpu.write_conf("reload_after_games", "on")
        with mock.patch.object(gpu, "running", lambda: True):
            gpu.gamemode("on")
        gpu.gamemode("off")
        self.assertEqual(self.loads, ["glm-4.7-flash-x"])
        self.assertIsNone(gpu.read_unloaded())

    def test_switched_off(self):
        gpu.write_conf("unload_for_games", "off")
        with mock.patch.object(gpu, "running", lambda: True):
            self.assertEqual(gpu.gamemode("on"), "unload_for_games is off")
        self.assertEqual(self.calls, [])

    def test_nothing_loaded(self):
        with mock.patch.object(gpu, "running", lambda: True), mock.patch.object(gpu, "lms_ps", lambda: []):
            self.assertEqual(gpu.gamemode("on"), "nothing loaded")
        self.assertEqual(self.calls, [])
        self.assertEqual(gpu.gamemode("off"), "nothing was unloaded")


class Settings(unittest.TestCase):
    """llm.json: the roles, the context and the slots."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        p = mock.patch.object(llm_models, "SETTINGS", os.path.join(self.dir.name, "llm.json"))
        p.start()
        self.addCleanup(p.stop)
        q = mock.patch.object(llm_models, "local_models", lambda: [
            llm_models.Model("gemma-4-e4b", "Gemma", "local", "google/gemma-4-e4b")])
        q.start()
        self.addCleanup(q.stop)

    def read(self):
        with open(llm_models.SETTINGS) as handle:
            return json.load(handle)

    def test_defaults(self):
        self.assertEqual(llm_models.local_options(), (llm_models.LOCAL_CONTEXT, None))
        self.assertEqual(llm_models.settings()["worker"], "default")

    def test_set_keeps_the_rest(self):
        llm_models.set_option("context", "49152")
        llm_models.set_option("parallel", "2")
        with self.assertRaises(ValueError):
            llm_models.set_option("worker", "gemma")        # a prefix is not taken for a setting
        self.assertEqual(llm_models.local_options(), (49152, 2))
        llm_models.set_option("quick", "gemma-4-e4b")
        llm_models.set_option("default", "opus")
        self.assertEqual(self.read(), {"context": 49152, "parallel": 2, "quick": "gemma-4-e4b",
                                       "default": "opus"})
        llm_models.set_option("parallel", "auto")
        self.assertNotIn("parallel", self.read())

    def test_refused(self):
        for key, value in (("context", "100"), ("parallel", "64"), ("quick", "nope"), ("colour", "x")):
            with self.assertRaises(ValueError):
                llm_models.set_option(key, value)
        with self.assertRaises(ValueError):
            llm_models.set_option("context", "lots")
        self.assertFalse(os.path.exists(llm_models.SETTINGS))

    def test_out_of_range_by_hand_is_the_default(self):
        with open(llm_models.SETTINGS, "w") as handle:
            json.dump({"context": 12, "parallel": "4", "quick": "haiku"}, handle)
        self.assertEqual(llm_models.local_options(), (llm_models.LOCAL_CONTEXT, None))


class QuickChoice(unittest.TestCase):
    GEMMA = llm_models.Model("gemma-4-e4b", "Gemma", "local", "google/gemma-4-e4b")

    def choose(self, verdict, gaming=False):
        calc = mock.Mock(fit_now=lambda m: verdict and {"verdict": verdict})
        with mock.patch.object(llm_models, "_gpu_module", lambda: calc), \
                mock.patch.object(llm_models, "_gamemode_on", lambda: gaming):
            return llm_models.quick_choice(self.GEMMA)

    def test_fits_or_loaded(self):
        self.assertEqual(self.choose("fits"), (self.GEMMA, ""))
        self.assertEqual(self.choose("tight"), (self.GEMMA, ""))
        self.assertEqual(self.choose(None), (self.GEMMA, ""))        # loaded already, or no card

    def test_gives_way_to_haiku(self):
        model, why = self.choose("won't fit")
        self.assertEqual(model.name, "haiku")
        self.assertIn("would not fit", why)
        model, why = self.choose("fits", gaming=True)
        self.assertEqual(model.name, "haiku")
        self.assertIn("gamemode", why)

    def test_claude_untouched_and_errors_harmless(self):
        haiku = llm_models.resolve("opus")
        self.assertEqual(llm_models.quick_choice(haiku), (haiku, ""))

        def broken():
            raise RuntimeError("calculator broke")
        with mock.patch.object(llm_models, "_gpu_module", broken), \
                mock.patch.object(llm_models, "_gamemode_on", lambda: False):
            self.assertEqual(llm_models.quick_choice(self.GEMMA), (self.GEMMA, ""))


class MakeRoom(unittest.TestCase):
    """ensure_local's _make_room: the idle smaller models give way, nothing else."""
    GLM = llm_models.Model("glm-4.7-flash", "GLM", "local", "glm-big")
    LOADED = [{"modelKey": "gemma-small", "identifier": "gemma-small", "status": "idle", "sizeBytes": 6e9},
              {"modelKey": "busy-small", "status": "generating", "sizeBytes": 2e9},
              {"modelKey": "other-big", "status": "idle", "sizeBytes": 30e9},
              {"modelKey": "embed", "type": "embedding", "status": "idle", "sizeBytes": 1e8}]

    def unloads(self, verdict):
        calls = []
        calc = mock.Mock(fit_now=lambda m: verdict and {"verdict": verdict})
        with mock.patch.object(llm_models, "_gpu_module", lambda: calc), \
                mock.patch.object(llm_models, "_read_cache",
                                  lambda: {"models": [{"modelKey": "glm-big", "sizeBytes": 21e9}]}), \
                mock.patch.object(llm_models, "_lms", lambda *a, **k: calls.append(a)):
            llm_models._make_room(self.GLM, self.LOADED, lambda text: None)
        return calls

    def test_only_idle_smaller_llms(self):
        self.assertEqual(self.unloads("won't fit"), [("unload", "gemma-small")])

    def test_nothing_when_it_fits(self):
        self.assertEqual(self.unloads("tight"), [])
        self.assertEqual(self.unloads(None), [])


class PageText(unittest.TestCase):
    def setUp(self):
        try:
            from settings_pages import ai            # needs GTK, not a display
        except Exception as exc:                   # noqa: BLE001
            raise unittest.SkipTest(f"settings_pages.ai not importable: {exc}")
        self.ai = ai

    def test_role_choices_keep_a_deleted_model(self):
        installed = [{"alias": "gemma-4-e4b", "size": 6.3e9}]
        names = [n for n, _ in self.ai.role_choices("qwen3.6-27b", installed)]
        self.assertEqual(names[:5], ["default", "fable", "opus", "sonnet", "haiku"])
        self.assertIn("gemma-4-e4b", names)
        self.assertEqual(names[-1], "qwen3.6-27b")
        self.assertIn("not installed", self.ai.role_choices("qwen3.6-27b", installed)[-1][1])
        self.assertEqual(len(self.ai.role_choices("haiku", installed)), 6)

    def test_chips_and_lines(self):
        self.assertEqual(self.ai.context_chips(40000)[3], ("40000", "39k"))
        self.assertEqual(self.ai.slot_chips(None, 4)[0], ("auto", "LM Studio's (4)"))
        self.assertIn("unloads in 3 min", self.ai.loaded_sub({"size": 21.6e9, "context": 32768, "parallel": 4,
                                                              "status": "idle", "ttl_left": 200}))
        self.assertIn("won't fit", self.ai.fit_text({"fit": gpu.fit(30 * GB, 0, 24 * GB)}))


if __name__ == "__main__":
    unittest.main()
