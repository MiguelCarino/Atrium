"""llm-bench.py: the plan of configurations, the llama-server command line's
spill, the streamed answer's timings, the tool-call and instruction checks,
the calculator's error and the recommendations. Pure functions and scratch
files only: no lms, no nvidia-smi, no server."""
import json
import os
import unittest
from unittest import mock

import helpers

bench = helpers.import_script("llm-bench.py")
GB = 1e9


def spares(table):
    """spare_of() from {(ctx, parallel): spare in GB}."""
    return lambda ctx, par: table[(ctx, par)] * GB


class Plan(unittest.TestCase):
    def test_all_fit_adds_the_smallest_larger_context_that_does_not(self):
        table = {(16384, 1): 5, (32768, 1): 4, (65536, 1): 1.5, (65536, 4): 1.1, (131072, 1): -2.7}
        self.assertEqual(bench.plan(spares(table), 262144), [
            (16384, 1, "run"), (32768, 1, "run"), (65536, 1, "run"), (65536, 4, "run"), (131072, 1, "spill")])

    def test_first_short_one_is_the_spill_and_far_short_ones_are_skipped(self):
        table = {(16384, 1): 0.4, (32768, 1): -1.2, (65536, 1): -4.6, (65536, 4): -4.6}
        self.assertEqual(bench.plan(spares(table)), [
            (16384, 1, "run"), (32768, 1, "spill"), (65536, 1, "skip"), (65536, 4, "skip")])

    def test_only_far_short_ones_still_runs_the_least_short_as_the_spill(self):
        table = {(16384, 1): -3.5, (32768, 1): -5, (65536, 1): -9, (65536, 4): -9.5}
        kinds = [k for _c, _p, k in bench.plan(spares(table))]
        self.assertEqual(kinds, ["spill", "skip", "skip", "skip"])

    def test_no_spill_within_the_model_context(self):
        table = {(16384, 1): 17, (32768, 1): 16, (65536, 1): 16, (65536, 4): 16, (131072, 1): 15}
        self.assertEqual(len(bench.plan(spares(table), 131072)), 4)

    def test_quick(self):
        table = {(32768, 1): 4, (65536, 4): 1, (131072, 1): -2}
        self.assertEqual(bench.plan(spares(table), 131072, quick=True),
                         [(32768, 1, "run"), (65536, 4, "run"), (131072, 1, "spill")])


class Spill(unittest.TestCase):
    ARGV = ["llama-server", "--model", "x.gguf", "--n-gpu-layers", "999999", "--n-cpu-moe", "0", "--kv-offload"]

    def test_all_on_the_card(self):
        self.assertEqual(bench.spill_from_argv(self.ARGV, 47), (False, "all on the card"))

    def test_fewer_layers(self):
        argv = list(self.ARGV)
        argv[4] = "39"
        self.assertEqual(bench.spill_from_argv(argv, 47), (True, "39 of 48 layers on the card"))

    def test_experts_in_ram_and_kv_in_ram(self):
        argv = self.ARGV[:6] + ["12", "--no-kv-offload"]
        spilled, detail = bench.spill_from_argv(argv, 47)
        self.assertTrue(spilled)
        self.assertIn("experts of 12 layers", detail)
        self.assertIn("KV cache in RAM", detail)


def sse(*chunks):
    return [("data: " + json.dumps(c) + "\n").encode() for c in chunks] + [b"data: [DONE]\n"]


class Stream(unittest.TestCase):
    def test_timings_and_usage(self):
        clock = iter([1.0, 1.5, 3.0, 3.1]).__next__
        lines = sse({"choices": [{"delta": {"role": "assistant"}}]},
                    {"choices": [{"delta": {"reasoning_content": "hm"}}]},
                    {"choices": [{"delta": {"content": "Hello"}}]},
                    {"choices": [], "usage": {"prompt_tokens": 8000, "completion_tokens": 256}})
        ans = bench.parse_stream([b": keep-alive\n"] + lines, 0.5, clock)
        self.assertEqual(ans["t_first"], 1.5)          # the reasoning delta counts as the first token
        self.assertEqual(ans["t_last"], 3.0)
        self.assertEqual(ans["ttft"], 1.0)
        self.assertEqual(ans["text"], "Hello")
        self.assertEqual((ans["prompt_tokens"], ans["completion_tokens"]), (8000, 256))
        pp, gen = bench.speeds(ans)
        self.assertEqual(pp, 8000)
        self.assertAlmostEqual(gen, 255 / 1.5)

    def test_no_tokens(self):
        ans = bench.parse_stream(sse({"choices": [], "usage": {"prompt_tokens": 5, "completion_tokens": 0}}), 0)
        self.assertIsNone(ans["ttft"])
        self.assertEqual(bench.speeds(ans), (None, None))


class Checks(unittest.TestCase):
    def call(self, name="get_weather", args='{"city": "Paris"}'):
        return {"tool_calls": [{"type": "function", "function": {"name": name, "arguments": args}}]}

    def test_tool(self):
        self.assertTrue(bench.tool_ok(self.call()))
        self.assertTrue(bench.tool_ok(self.call(args='{"city": "Paris, France"}')))
        self.assertFalse(bench.tool_ok(self.call(args='{"city": ')))
        self.assertFalse(bench.tool_ok(self.call(name="search")))
        self.assertFalse(bench.tool_ok({"content": '<tool_call>{"name": "get_weather"}</tool_call>'}))
        self.assertFalse(bench.tool_ok(None))

    def test_instruction(self):
        for text in ("BANANA 6", "banana 6.", '"BANANA 6"', "<think>count</think>\nBANANA 6", "**BANANA** 6"):
            self.assertTrue(bench.instruction_ok(text), text)
        for text in ("BANANA six", "BANANA 6 letters", "", None, "Sure! BANANA 6"):
            self.assertFalse(bench.instruction_ok(text), text)


def run_row(alias, ctx, par, vram, need, gen, pp=2000.0, agg=None, size=17e9, **kw):
    return dict({"alias": alias, "ctx": ctx, "parallel": par, "vram": vram * GB, "size": size,
                 "predicted": {"need": need * GB}, "gen_tps": gen, "pp_tps": pp, "agg_tps": agg}, **kw)


class Calculator(unittest.TestCase):
    def test_mean_per_model_and_spills_left_out(self):
        runs = [run_row("a", 16384, 1, 5.0, 7.0, 100), run_row("a", 32768, 1, 5.5, 7.5, 100),
                run_row("b", 16384, 1, 18.0, 17.0, 30),
                run_row("b", 131072, 1, 22.0, 27.0, 5, spilled=True)]
        c = bench.calculator_check(runs)
        self.assertEqual(c["n"], 3)
        self.assertEqual(c["per_model"], {"a": -2.0, "b": 1.0})
        self.assertAlmostEqual(c["mean_gb"], -1.0)
        self.assertFalse(c["consistent"])

    def test_consistent(self):
        runs = [run_row("a", 16384, 1, 5.0, 7.0, 100), run_row("b", 16384, 1, 15.0, 17.0, 30)]
        self.assertTrue(bench.calculator_check(runs)["consistent"])

    def test_nothing_measured(self):
        self.assertEqual(bench.calculator_check([{"alias": "a", "skipped": "x"}])["n"], 0)


class Recommend(unittest.TestCase):
    RUNS = [
        run_row("small", 16384, 1, 5.1, 7.1, 123, pp=9000, size=6e9),
        run_row("small", 65536, 1, 6.0, 7.9, 137, pp=9900, size=6e9),
        run_row("small", 65536, 4, 6.1, 8.0, 131, pp=9600, agg=240, size=6e9),
        run_row("big", 32768, 1, 19.0, 20.5, 38, pp=2100),
        run_row("big", 65536, 1, 21.0, 22.7, 37, pp=2000),
        run_row("big", 65536, 4, 21.5, 23.1, 36, pp=1900, agg=110),
        run_row("big", 131072, 1, 23.0, 27.0, 6, pp=300, spilled=True),
        run_row("moe", 16384, 1, 19.2, 23.8, 25, pp=1600, size=21e9, spilled=True),
    ]
    Q = {"small": {"tool_ok": True, "instr_ok": True}, "big": {"tool_ok": True, "instr_ok": True},
         "moe": {"tool_ok": True, "instr_ok": False}}

    def test_roles(self):
        rec = bench.recommend(self.RUNS, self.Q, {"small": 6e9, "big": 17e9, "moe": 21e9})
        self.assertEqual((rec["default"]["model"], rec["default"]["ctx"]), ("big", 65536))
        self.assertIn("19k prompt", rec["default"]["why"])
        self.assertEqual(rec["quick"]["model"], "small")
        self.assertEqual((rec["worker"]["model"], rec["worker"]["parallel"]), ("small", 4))

    def test_default_needs_the_tool_call_and_24k_a_slot(self):
        q = dict(self.Q, big={"tool_ok": False, "instr_ok": True})
        self.assertEqual(bench.recommend(self.RUNS, q)["default"]["model"], "small")
        only_wide = [r for r in self.RUNS if r["parallel"] == 4 or r.get("spilled")]
        self.assertIsNone(bench.recommend(only_wide, self.Q)["default"]["model"])

    def test_too_slow_a_big_model_gives_way(self):
        runs = [dict(r, gen_tps=8) if r["alias"] == "big" else r for r in self.RUNS]
        self.assertEqual(bench.recommend(runs, self.Q)["default"]["model"], "small")

    def test_nothing_passes(self):
        rec = bench.recommend([], {})
        self.assertEqual({r["model"] for r in rec.values()}, {None})


class LoadFailure(unittest.TestCase):
    def test_out_of_card_memory(self):
        log = ("E ggml_backend_cuda_buffer_type_alloc_buffer: allocating 8192.00 MiB on device 0: cudaMalloc "
               "failed: out of memory\nE llama_init_from_model: failed to initialize the context: failed to "
               "allocate buffer for kv cache\n")
        self.assertIn("out of card memory for the KV cache", bench.load_failure(log))

    def test_startup_error_or_nothing(self):
        log = 'LMSTUDIO_STARTUP_ERROR:{"schemaVersion":1,"code":"x","message":"Bad model"}\n'
        self.assertEqual(bench.load_failure(log), "Bad model")
        self.assertEqual(bench.load_failure("all fine"), "")


class Results(unittest.TestCase):
    def test_merge_keeps_the_other_models(self):
        old = [{"alias": "a", "ctx": 1}, {"alias": "b", "ctx": 1}]
        self.assertEqual(bench.merge(old, [{"alias": "b", "ctx": 2}], ["b"]),
                         [{"alias": "a", "ctx": 1}, {"alias": "b", "ctx": 2}])

    def test_write_read_round_trip(self):
        path = os.path.join(helpers.SCRATCH, "bench", "r.json")
        bench.write_results({"runs": [1]}, path)
        self.assertEqual(bench.read_results(path), {"runs": [1]})
        self.assertEqual(bench.read_results(path + ".missing"), {})

    def test_table_and_show(self):
        data = {"runs": Recommend.RUNS + [{"alias": "moe", "ctx": 65536, "parallel": 1,
                                           "predicted": {"need": 28.8 * GB}, "skipped": "4.6 GB short"}],
                "quality": Recommend.Q}
        data["recommend"] = bench.recommend(data["runs"], data["quality"])
        data["calculator"] = bench.calculator_check(data["runs"])
        rows = bench.table_rows(data)
        self.assertEqual(rows[2], ("small", "64k", "4", "6.1", "8.0", "9600", "131.0", "240", "-", "yes", ""))
        self.assertEqual(rows[-1][3], "-")
        self.assertEqual(rows[-1][-1], "4.6 GB short")
        self.assertTrue(rows[6][-1].startswith("spilled"))
        text = bench.show_text(data)
        self.assertIn("worker", text)
        self.assertIn("calculator:", text)
        self.assertEqual(bench.show_text({}), "no results yet: llm-bench.py run")

    def test_recheck_redoes_the_predictions(self):
        runs = [dict(r, key=r["alias"]) for r in Recommend.RUNS[:3]]
        data = bench.recheck({"runs": runs, "quality": Recommend.Q},
                             lambda key, ctx, par: {"need": 5.0 * GB} if key == "small" else None)
        self.assertEqual(data["runs"][0]["predicted"], {"need": 5.0 * GB})
        self.assertEqual(data["runs"][0]["predicted_before"], {"need": 7.1 * GB})
        self.assertAlmostEqual(data["calculator"]["per_model"]["small"], (5.1 + 6.0 + 6.1) / 3 - 5.0, places=2)
        self.assertEqual(data["recommend"]["quick"]["model"], "small")

    def test_chat_models_skips_embeddings_and_missing_files(self):
        rows = [{"type": "llm", "modelKey": "qwen/qwen3.8-27b", "path": "qwen/qwen3.8-27b"},
                {"type": "llm", "modelKey": "google/gemma-4-e4b", "path": "google/gemma-4-e4b"},
                {"type": "embedding", "modelKey": "text-embedding-nomic", "path": "n/n/n.gguf"}]
        fake = mock.Mock()
        fake.model_file = lambda p: None if "gemma" in p else "/x.gguf"
        with mock.patch.object(bench, "_gpu_module", return_value=fake):
            self.assertEqual([a for _r, a in bench.chat_models(rows)], ["qwen3.8-27b"])
            self.assertEqual(bench.chat_models(rows, ["gemma"]), [])
            self.assertEqual([a for _r, a in bench.chat_models(rows, ["qwen"])], ["qwen3.8-27b"])


if __name__ == "__main__":
    unittest.main()
