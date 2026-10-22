#!/usr/bin/env python3
"""A one-off benchmark of the local models (LM Studio) on this card: how
long each takes to load, how much of the card it really takes (against the
fit calculator in llm-gpu.py), how fast it reads and writes, what four
answers at once give, and whether it makes a tool call and follows a plain
instruction. Settings > AI & models shows the results ("Benchmark") and
runs it again.

    llm-bench.py run [--models K,...] [--quick]
                         every installed chat model (embedding models and
                         ones whose files are gone are skipped), or only the
                         ones named (alias, key or unambiguous start); their
                         earlier results are replaced, the others' kept.
                         --quick: 32k with 1 slot and 64k with 4 only (and
                         the spill case)
    llm-bench.py show [--json]
                         the results as a table and the recommendations
    llm-bench.py recheck the calculator's predictions worked out again
                         (after a change to llm-gpu.py) against the VRAM
                         measured, nothing loaded; the earlier prediction
                         kept as "predicted_before"

Results: ~/.local/state/hypr/llm-bench.json. What it does per model:

    configurations  contexts 16k, 32k, 64k with 1 slot, and 64k with 4.
                    One the calculator says will not fit by more than
                    SKIP_OVER (3 GB) is skipped; the first one that will not
                    fit (or, when all fit, the smallest larger context that
                    does not) is run anyway, once, to show what spilling to
                    RAM really costs
    each            `lms load KEY -y -c CTX --parallel N --ttl`, timed; the
                    card's memory the new llama-server holds (nvidia-smi)
                    against the calculator's "needed"; spilled = its
                    --n-gpu-layers below the model's layers, or
                    --n-cpu-moe above 0 (LM Studio's choice, from /proc);
                    one streamed ~8k-token prompt (the desktop scripts' own
                    docstrings, a fresh nonce first so no cache helps) and a
                    256-token answer: TTFT, prompt tokens/s (prompt tokens /
                    TTFT), generation tokens/s (after the first token)
    4 slots         the same 4 times at once: tokens/s added up
    quality         once per model (the first configuration that did not
                    spill): one tool-call request (a valid get_weather call
                    for Paris?) and one instruction with a checkable answer,
                    reasoning_effort "none"

Every configuration is unloaded after; a load is not started with less than
MIN_RAM (8 GB) available, and one is stopped when RAM drops under
PANIC_RAM during it. What was loaded before (other than embedding models,
which are left alone) is loaded again at the end. llm.json's roles are not
changed: the recommendations are only written into the results.
"""
import ast
import glob
import importlib.util
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import llm_models  # noqa: E402

HOME = os.path.expanduser("~")
STATE_DIR = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.join(HOME, ".local", "state"), "hypr")
RESULTS = os.path.join(STATE_DIR, "llm-bench.json")
GB = 1e9
CONTEXTS = [16384, 32768, 65536]
WIDE = (65536, 4)                   # the configuration with 4 slots
QUICK = [(32768, 1), (65536, 4)]
SPILL_TRY = [131072, 196608, 262144]
SKIP_OVER = 3 * GB                  # skip a configuration short by more than this
MIN_RAM = 8 * GB                    # MemAvailable before a load
PANIC_RAM = 2.5 * GB                # MemAvailable during one: stop it
PROMPT_TOKENS = 8000
CHARS_PER_TOKEN = 3.6               # first guess, corrected by the first answer's usage
GEN_TOKENS = 256
TTL = 900
BUDGET = 42 * 60                    # s: configurations after this are skipped
SLOT_NEED = 24 * 1024               # a chat with tools on a local model: tokens per slot
INSTRUCTION = ("Reply with exactly two things separated by one space: the word banana in capital letters, "
               "then the number of letters in it. No other text.")
INSTRUCTION_ANSWER = "BANANA 6"
TOOL = {"type": "function", "function": {
    "name": "get_weather", "description": "The current weather in a city",
    "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}}


def _gpu_module():
    spec = importlib.util.spec_from_file_location("llm_gpu", os.path.join(HERE, "llm-gpu.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# -- pure: planning, parsing, scoring -----------------------------------------------
def plan(spare_of, max_context=None, quick=False):
    """[(ctx, parallel, kind)] for one model; kind "run", "spill" or
    "skip". spare_of(ctx, parallel) is the calculator's spare bytes (room -
    need; negative: will not fit)."""
    base = QUICK if quick else [(c, 1) for c in CONTEXTS] + [WIDE]
    out, spill = [], False
    for ctx, par in base:
        spare = spare_of(ctx, par)
        if spare >= 0:
            out.append((ctx, par, "run"))
        elif not spill and spare >= -SKIP_OVER:
            out.append((ctx, par, "spill"))
            spill = True
        else:
            out.append((ctx, par, "skip"))
    if not spill:
        skipped = [(c, p) for c, p, kind in out if kind == "skip"]
        if skipped:     # the least short of the skipped ones
            ctx, par = max(skipped, key=lambda cp: spare_of(*cp))
            out = [(c, p, "spill" if (c, p) == (ctx, par) else kind) for c, p, kind in out]
        else:
            for ctx in SPILL_TRY:
                if max_context and ctx > max_context:
                    break
                if spare_of(ctx, 1) < 0:
                    out.append((ctx, 1, "spill"))
                    break
    return out


def spill_from_argv(argv, layers):
    """(spilled, detail) from a llama-server command line: --n-gpu-layers
    below the model's layers + 1 (the output layer), or --n-cpu-moe > 0
    (experts kept in RAM), or --gpu off."""
    def arg(flag):
        if flag in argv and argv.index(flag) + 1 < len(argv):
            return argv[argv.index(flag) + 1]
        return None
    bits = []
    ngl, moe = arg("--n-gpu-layers") or arg("-ngl"), arg("--n-cpu-moe")
    spilled = False
    try:
        if ngl is not None and layers and int(ngl) < layers + 1:
            spilled = True
            bits.append(f"{int(ngl)} of {layers + 1} layers on the card")
    except ValueError:
        pass
    try:
        if moe is not None and int(moe) > 0:
            spilled = True
            bits.append(f"experts of {int(moe)} layers in RAM")
    except ValueError:
        pass
    if "--no-kv-offload" in argv:
        spilled = True
        bits.append("KV cache in RAM")
    return spilled, "; ".join(bits) or "all on the card"


def parse_stream(lines, t_start, clock=time.monotonic):
    """A streamed /v1/chat/completions answer (an iterable of SSE lines,
    bytes or str, read as they come) -> {ttft, t_first, t_last, prompt_tokens,
    completion_tokens, text}. A delta of content or reasoning_content counts
    as a token arriving; usage comes from the last chunk."""
    out = {"t_first": None, "t_last": None, "prompt_tokens": None, "completion_tokens": None, "text": ""}
    for raw in lines:
        line = raw.decode(errors="replace") if isinstance(raw, bytes) else raw
        line = line.strip()
        if not line.startswith("data:"):
            continue
        body = line[5:].strip()
        if body == "[DONE]":
            break
        try:
            chunk = json.loads(body)
        except ValueError:
            continue
        now = clock()
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or {}
            piece = (delta.get("content") or "") + (delta.get("reasoning_content") or "") + \
                (delta.get("reasoning") or "")
            if piece:
                if out["t_first"] is None:
                    out["t_first"] = now
                out["t_last"] = now
                out["text"] += delta.get("content") or ""
        usage = chunk.get("usage")
        if usage:
            out["prompt_tokens"] = usage.get("prompt_tokens")
            out["completion_tokens"] = usage.get("completion_tokens")
    out["ttft"] = None if out["t_first"] is None else out["t_first"] - t_start
    return out


def speeds(answer):
    """(prompt tokens/s, generation tokens/s) from parse_stream()'s answer;
    None where it cannot say."""
    pp = gen = None
    if answer.get("ttft") and answer.get("prompt_tokens"):
        pp = answer["prompt_tokens"] / answer["ttft"]
    n = answer.get("completion_tokens") or 0
    if n > 1 and answer.get("t_first") is not None and answer["t_last"] > answer["t_first"]:
        gen = (n - 1) / (answer["t_last"] - answer["t_first"])
    return pp, gen


def tool_ok(message):
    """A valid get_weather call for Paris in a chat message?"""
    for call in (message or {}).get("tool_calls") or []:
        fn = call.get("function") or {}
        if fn.get("name") != "get_weather":
            continue
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except ValueError:
            return False
        return isinstance(args, dict) and "paris" in str(args.get("city", "")).lower()
    return False


def instruction_ok(text):
    """The checkable answer, allowing case, quotes, a final period and a
    thinking block before it."""
    text = re.sub(r"(?s)<think>.*?</think>", "", text or "")
    words = re.sub(r"[\"'`*.!]", "", text).split()
    return " ".join(words).upper() == INSTRUCTION_ANSWER


def measured(r):
    """The card's memory a run's llama-server held: after the load, or after
    the first answer when its buffers grew."""
    return max(r.get("vram") or 0, r.get("vram_after_run") or 0)


def calculator_check(runs):
    """How far the fit calculator was off: measured VRAM - predicted need, for
    the runs that did not spill. {"n", "mean_gb", "per_model": {alias:
    mean_gb}, "consistent": all the same sign and past 1.5 GB}."""
    errs = {}
    for r in runs:
        if r.get("vram") and r.get("predicted") and not r.get("spilled") and not r.get("error"):
            errs.setdefault(r["alias"], []).append((measured(r) - r["predicted"]["need"]) / GB)
    flat = [e for v in errs.values() for e in v]
    if not flat:
        return {"n": 0, "mean_gb": None, "per_model": {}, "consistent": False}
    mean = sum(flat) / len(flat)
    per = {a: round(sum(v) / len(v), 2) for a, v in errs.items()}
    consistent = abs(mean) > 1.5 and all((e > 0) == (mean > 0) and abs(e) > 1.5 for e in flat)
    return {"n": len(flat), "mean_gb": round(mean, 2), "per_model": per, "consistent": consistent}


def _good(r):
    return not r.get("error") and not r.get("skipped") and not r.get("spilled") and r.get("gen_tps")


def recommend(runs, quality, sizes=None):
    """{role: {"model", "ctx", "parallel", "why"} or {"model": None, "why"}}
    from the runs: default = the chat window's model (tool call passes,
    a configuration with >= 24k per slot on the card; the biggest such model
    whose answer comes at >= 15 tokens/s, then the fastest); quick = the
    soonest short answer (instruction passes: 500 prompt tokens and 150
    answer tokens worked out from its speeds, smaller VRAM on a tie);
    worker = the most tokens/s four at once (64k with 4 slots, on the card,
    instruction passes)."""
    sizes = sizes or {}
    out = {}
    q = quality or {}

    # default
    cands = [r for r in runs if _good(r) and r["ctx"] // r["parallel"] >= SLOT_NEED
             and (q.get(r["alias"]) or {}).get("tool_ok")]
    if cands:
        best_per = {}
        for r in cands:     # per model, its fastest qualifying configuration with the most context
            cur = best_per.get(r["alias"])
            if cur is None or (r["ctx"], r["gen_tps"]) > (cur["ctx"], cur["gen_tps"]):
                best_per[r["alias"]] = r
        usable = [r for r in best_per.values() if r["gen_tps"] >= 15] or list(best_per.values())
        pick = max(usable, key=lambda r: (sizes.get(r["alias"], r.get("size") or 0), r["gen_tps"]))
        read_s = 19000 / pick["pp_tps"] if pick.get("pp_tps") else None
        out["default"] = {"model": pick["alias"], "ctx": pick["ctx"], "parallel": pick["parallel"], "why": (
            f"the biggest model that passes the tool call and stays on the card at {pick['ctx'] // 1024}k "
            f"({pick['ctx'] // pick['parallel'] // 1024}k a slot): {pick['gen_tps']:.0f} tokens/s written, "
            f"{pick['pp_tps']:.0f} read" + (f" -- a ~19k prompt in ~{read_s:.0f} s" if read_s else "")
            + f", {pick['vram'] / GB:.1f} GB of the card")}
    else:
        out["default"] = {"model": None, "why": "no model passed the tool call with >= 24k a slot on the card"}

    # quick
    cands = [r for r in runs if _good(r) and r["parallel"] == 1 and r.get("pp_tps")
             and (q.get(r["alias"]) or {}).get("instr_ok")]
    if cands:
        def secs(r):
            return 500 / r["pp_tps"] + 150 / r["gen_tps"]
        pick = min(cands, key=lambda r: (round(secs(r), 1), r.get("vram") or 0))
        out["quick"] = {"model": pick["alias"], "ctx": pick["ctx"], "parallel": 1, "why": (
            f"the soonest short answer: {pick['gen_tps']:.0f} tokens/s written, a 150-token answer to a short "
            f"question in ~{secs(pick):.1f} s, {pick['vram'] / GB:.1f} GB at {pick['ctx'] // 1024}k")}
    else:
        out["quick"] = {"model": None, "why": "no model passed the instruction check"}

    # worker
    cands = [r for r in runs if _good(r) and r["parallel"] >= 4 and r.get("agg_tps")
             and (q.get(r["alias"]) or {}).get("instr_ok")]
    if cands:
        pick = max(cands, key=lambda r: r["agg_tps"])
        out["worker"] = {"model": pick["alias"], "ctx": pick["ctx"], "parallel": pick["parallel"], "why": (
            f"the most written four at once: {pick['agg_tps']:.0f} tokens/s together "
            f"({pick['agg_tps'] / pick['gen_tps']:.1f}x one alone), {pick['ctx'] // pick['parallel'] // 1024}k "
            f"a slot, {pick['vram'] / GB:.1f} GB of the card")}
    else:
        out["worker"] = {"model": None, "why": "no 4-slot configuration ran on the card and passed"}
    return out


def load_failure(log_text):
    """Why llama-server gave up, from the end of LM Studio's server log, or
    "" when it does not say."""
    tail = log_text[-200000:]
    if "cudaMalloc failed: out of memory" in tail:
        what = "the KV cache" if "allocate buffer for kv cache" in tail else "its buffers"
        return f"out of card memory for {what} (LM Studio kept every layer on the card instead of spilling)"
    m = re.findall(r'LMSTUDIO_STARTUP_ERROR:\{.*?"message":"([^"]+)"', tail)
    return m[-1] if m else ""


def server_log_tail():
    files = sorted(glob.glob(os.path.join(HOME, ".lmstudio", "server-logs", "*", "*.log")), key=os.path.getmtime)
    if not files:
        return ""
    try:
        with open(files[-1], "rb") as handle:
            handle.seek(max(0, os.path.getsize(files[-1]) - 200000))
            return handle.read().decode(errors="replace")
    except OSError:
        return ""


def merge(old_runs, new_runs, models):
    """The new runs, and the old ones of the models not run this time."""
    return [r for r in old_runs if r.get("alias") not in models] + new_runs


# -- the machine ---------------------------------------------------------------------
def mem_available():
    try:
        with open("/proc/meminfo") as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        pass
    return 0


def smi_apps():
    try:
        out = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,used_memory",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    apps = {}
    for line in out.strip().splitlines():
        bits = [b.strip() for b in line.split(",")]
        try:
            apps[int(bits[0])] = int(bits[-1]) * 2**20
        except (ValueError, IndexError):
            pass
    return apps


def smi_used():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10).stdout
        used, total = (int(x) * 2**20 for x in out.strip().splitlines()[0].split(","))
        return used, total
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return 0, 0


def server_argv(pid):
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as handle:
            return handle.read().decode(errors="replace").split("\0")
    except OSError:
        return []


def rss(pid):
    try:
        with open(f"/proc/{pid}/status") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        pass
    return None


def lms(*args, timeout=60):
    return subprocess.run([llm_models.LMS, *args], capture_output=True, text=True, timeout=timeout)


def lms_ps():
    try:
        return [r for r in llm_models._json_out(lms("ps", "--json").stdout) or [] if isinstance(r, dict)]
    except (OSError, subprocess.SubprocessError, ValueError):
        return []


def lms_ls():
    try:
        out = lms("ls", "--json", timeout=60).stdout
        return [r for r in json.loads(out[out.index("["):]) if isinstance(r, dict)]
    except (OSError, subprocess.SubprocessError, ValueError):
        return []


def port():
    return llm_models.server_port()


def ensure_server():
    state = llm_models._json_out(lms("server", "status", "--json").stdout) or {}
    if not state.get("running"):
        lms("server", "start", timeout=90)


def synthetic_text(chars):
    """The desktop scripts' own docstrings (no personal data), repeated to
    `chars` characters."""
    pieces = []
    for path in sorted(glob.glob(os.path.join(HERE, "*.py")) + glob.glob(os.path.join(HERE, "*", "*.py"))):
        try:
            tree = ast.parse(open(path, encoding="utf-8").read())
        except (OSError, SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
                doc = ast.get_docstring(node)
                if doc and len(doc) > 80:
                    pieces.append(doc)
    text = "\n\n".join(pieces) or "The quick brown fox jumps over the lazy dog. " * 100
    while len(text) < chars:
        text += "\n\n" + text
    return text[:chars]


class Bench:
    def __init__(self, quick=False, log=print):
        self.gpu = _gpu_module()
        self.quick = quick
        self.log = log
        self.cpt = CHARS_PER_TOKEN
        self.base = None
        self.started = time.monotonic()
        self.n = 0

    def url(self, path):
        return f"http://localhost:{port()}/v1/{path}"

    def prompt(self, tokens=PROMPT_TOKENS):
        if self.base is None:
            self.base = synthetic_text(int(PROMPT_TOKENS * 6))
        text = self.base[:int(tokens * self.cpt)]
        return (f"[{secrets.token_hex(8)}] Below are notes from a desktop's scripts.\n\n{text}\n\n"
                "Now write a long, detailed walkthrough of what these scripts do, section by section.")

    def post(self, body, stream=False, timeout=600):
        req = urllib.request.Request(self.url("chat/completions"), data=json.dumps(body).encode(),
                                     headers={"content-type": "application/json"})
        return urllib.request.urlopen(req, timeout=timeout)

    def ask_stream(self, ident, tokens=PROMPT_TOKENS, max_tokens=GEN_TOKENS):
        body = {"model": ident, "messages": [{"role": "user", "content": self.prompt(tokens)}],
                "max_tokens": max_tokens, "temperature": 0.7, "stream": True,
                "stream_options": {"include_usage": True}, "reasoning_effort": "none"}
        t0 = time.monotonic()
        with self.post(body, stream=True) as resp:
            ans = parse_stream(resp, t0)
        ans["t_start"] = t0
        if ans.get("prompt_tokens") and tokens == PROMPT_TOKENS and abs(ans["prompt_tokens"] - tokens) > 400:
            self.cpt *= tokens / ans["prompt_tokens"]      # nearer the next time
        return ans

    def ask_plain(self, ident, content, tools=None, max_tokens=400):
        body = {"model": ident, "messages": [{"role": "user", "content": content}], "max_tokens": max_tokens,
                "temperature": 0, "reasoning_effort": "none"}
        if tools:
            body["tools"] = tools
        with self.post(body, timeout=300) as resp:
            data = json.loads(resp.read())
        return ((data.get("choices") or [{}])[0]).get("message") or {}

    def quality(self, ident):
        out = {}
        try:
            msg = self.ask_plain(ident, "What is the weather in Paris right now? Use the tool.", [TOOL])
            out["tool_ok"] = tool_ok(msg)
            out["tool_detail"] = json.dumps(msg.get("tool_calls") or msg.get("content") or "")[:200]
        except (OSError, ValueError) as exc:
            out["tool_ok"], out["tool_detail"] = False, f"error: {exc}"
        try:
            msg = self.ask_plain(ident, INSTRUCTION)
            out["instr_ok"] = instruction_ok(msg.get("content"))
            out["instr_detail"] = (msg.get("content") or "")[:120]
        except (OSError, ValueError) as exc:
            out["instr_ok"], out["instr_detail"] = False, f"error: {exc}"
        return out

    def predicted(self, row, ctx, par):
        meta = self.gpu.meta_for(row.get("path"))
        kv, how = self.gpu.estimate(row, ctx, par, meta)
        _used, total = smi_used()
        f = self.gpu.fit(self.gpu.card_size(row, meta), kv, total)
        return {"need": f["need"], "kv": kv, "kv_how": how, "spare": f["spare"], "verdict": f["verdict"]}, meta

    def configure(self, row, ctx, par, kind, alias, meta):
        """Load, measure, unload one configuration: its result row."""
        res = {"alias": alias, "key": row["modelKey"], "size": row.get("sizeBytes") or 0, "ctx": ctx,
               "parallel": par, "kind": kind}
        pred, _ = self.predicted(row, ctx, par)
        res["predicted"] = pred
        if kind == "skip":
            res["skipped"] = f"the calculator says it is {-pred['spare'] / GB:.1f} GB short"
            return res
        if time.monotonic() - self.started > BUDGET:
            res["skipped"] = "out of time"
            return res
        avail = mem_available()
        if avail < MIN_RAM:
            res["skipped"] = f"only {avail / GB:.1f} GB of RAM available"
            return res
        others = [r.get("identifier") for r in lms_ps() if r.get("type") == "llm"]
        if others:
            res["others_loaded"] = others
        self.n += 1
        ident = f"bench-{secrets.token_hex(3)}"
        before = set(smi_apps())
        used0, _total = smi_used()
        self.log(f"  {alias} {ctx // 1024}k x{par} ({kind}): loading…")
        t0 = time.monotonic()
        proc = subprocess.Popen([llm_models.LMS, "load", row["modelKey"], "-y", "-c", str(ctx), "--parallel",
                                 str(par), "--ttl", str(TTL), "--identifier", ident],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        panic = []

        def watch():
            while proc.poll() is None:
                if mem_available() < PANIC_RAM:
                    panic.append(mem_available())
                    proc.kill()
                    return
                time.sleep(0.5)
        threading.Thread(target=watch, daemon=True).start()
        try:
            out = proc.communicate(timeout=400)[0].decode(errors="replace")
        except subprocess.TimeoutExpired:
            proc.kill()
            out = "timed out"
        res["load_s"] = round(time.monotonic() - t0, 1)
        try:
            if panic or proc.returncode:
                tail = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", out).replace("\r", "\n").strip().splitlines()
                why = load_failure(server_log_tail())
                res["error"] = ("stopped: RAM fell to %.1f GB" % (panic[0] / GB)) if panic else \
                    "load failed: " + (why or (tail[-1] if tail else f"exit {proc.returncode}"))
                return res
            time.sleep(1.5)
            apps = smi_apps()
            new = [p for p in apps if p not in before and os.path.basename(server_argv(p)[0] if
                                                                          server_argv(p) else "") == "llama-server"]
            pid = new[0] if new else None
            used1, _ = smi_used()
            res["vram_total_delta"] = used1 - used0
            res["vram"] = apps.get(pid) if pid else used1 - used0
            if pid:
                arch = (meta or {}).get("general.architecture") or ""
                layers = (meta or {}).get(f"{arch}.block_count")
                res["spilled"], res["spill_detail"] = spill_from_argv(server_argv(pid), layers)
                res["rss"] = rss(pid)
            loaded = [r for r in lms_ps() if r.get("identifier") == ident]
            if loaded:
                res["ctx_loaded"] = loaded[0].get("contextLength")
                res["parallel_loaded"] = loaded[0].get("parallel")
            self.log(f"    loaded in {res['load_s']} s, {(res['vram'] or 0) / GB:.1f} GB "
                     f"(predicted {pred['need'] / GB:.1f}), {res.get('spill_detail')}")
            ans = self.ask_stream(ident)
            pp, gen = speeds(ans)
            res.update({"prompt_tokens": ans["prompt_tokens"], "completion_tokens": ans["completion_tokens"],
                        "ttft_s": round(ans["ttft"], 2) if ans["ttft"] else None,
                        "pp_tps": round(pp, 1) if pp else None, "gen_tps": round(gen, 1) if gen else None})
            if pid:
                res["vram_after_run"] = smi_apps().get(pid)
            self.log(f"    pp {res['pp_tps']} t/s, gen {res['gen_tps']} t/s, ttft {res['ttft_s']} s")
            if par >= 4 and not res.get("spilled"):
                answers = [None] * 4
                t_wall = time.monotonic()

                def one(i):
                    try:
                        answers[i] = self.ask_stream(ident)
                    except (OSError, ValueError) as exc:
                        answers[i] = {"error": str(exc)}
                threads = [threading.Thread(target=one, args=(i,)) for i in range(4)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()
                wall = time.monotonic() - t_wall
                ok = [a for a in answers if a and not a.get("error") and a.get("completion_tokens")]
                if ok:
                    gens = [speeds(a)[1] or 0 for a in ok]
                    res["agg_tps"] = round(sum(gens), 1)
                    res["agg_wall_tps"] = round(sum(a["completion_tokens"] for a in ok) / wall, 1)
                    res["agg_ttft_s"] = round(max(a["ttft"] or 0 for a in ok), 2)
                    res["agg_n"] = len(ok)
                    self.log(f"    x4: {res['agg_tps']} t/s together, {res['agg_wall_tps']} end to end")
            return res
        except (OSError, ValueError) as exc:
            res["error"] = f"request failed: {exc}"
            return res
        finally:
            lms("unload", ident)
            time.sleep(1)

    def run(self, rows):
        runs, quality = [], {}
        for row, alias in rows:
            self.log(f"{alias}")
            meta = self.gpu.meta_for(row.get("path"))

            def spare_of(ctx, par, row=row):
                return self.predicted(row, ctx, par)[0]["spare"]
            for ctx, par, kind in plan(spare_of, row.get("maxContextLength"), self.quick):
                res = self.configure_with_quality(row, ctx, par, kind, alias, meta, quality)
                runs.append(res)
        return runs, quality

    def configure_with_quality(self, row, ctx, par, kind, alias, meta, quality):
        """configure(), with the quality checks run in it the first time a
        model is loaded without spilling."""
        if alias in quality or kind != "run":
            return self.configure(row, ctx, par, kind, alias, meta)
        orig = self.ask_stream

        def wrapped(ident, *a, **kw):
            ans = orig(ident, *a, **kw)
            if alias not in quality:
                quality[alias] = self.quality(ident)
                self.log(f"    tool call {'ok' if quality[alias]['tool_ok'] else 'FAILED'}, instruction "
                         f"{'ok' if quality[alias]['instr_ok'] else 'FAILED'}")
            return ans
        self.ask_stream = wrapped
        try:
            return self.configure(row, ctx, par, kind, alias, meta)
        finally:
            self.ask_stream = orig


# -- the commands ---------------------------------------------------------------------
def read_results(path=None):
    try:
        with open(path or RESULTS) as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_results(data, path=None):
    path = path or RESULTS
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as handle:
        json.dump(data, handle, indent=1)
    os.replace(tmp, path)


def chat_models(rows, names=None):
    """[(row, alias)]: lms ls's llm rows whose weights are on disk, the ones
    `names` picks (aliases, keys or starts) when given."""
    gpu = _gpu_module()
    aliases = llm_models._aliases([r["modelKey"] for r in rows if r.get("type") == "llm"])
    out = []
    for r in rows:
        if r.get("type") != "llm" or not r.get("modelKey"):
            continue
        if not gpu.model_file(r.get("path")):
            continue
        alias = aliases[r["modelKey"]]
        if names and not any(n.lower() in (alias, r["modelKey"].lower()) or alias.startswith(n.lower())
                             for n in names):
            continue
        out.append((r, alias))
    return sorted(out, key=lambda ra: ra[1])


def restore(before, log=print):
    """Load again the chat models that were loaded before and are not now."""
    now = {r.get("identifier") for r in lms_ps()}
    for r in before:
        if r.get("type") != "llm" or r.get("identifier") in now:
            continue
        args = ["load", r["modelKey"], "-y", "--identifier", r.get("identifier") or r["modelKey"]]
        if r.get("contextLength"):
            args += ["-c", str(r["contextLength"])]
        if r.get("parallel"):
            args += ["--parallel", str(r["parallel"])]
        if r.get("ttlMs"):
            args += ["--ttl", str(int(r["ttlMs"] / 1000))]
        log(f"loading {r['modelKey']} again, as it was")
        lms(*args, timeout=400)


def cmd_run(argv):
    names = None
    if "--models" in argv and argv.index("--models") + 1 < len(argv):
        names = [n for n in argv[argv.index("--models") + 1].split(",") if n]
    quick = "--quick" in argv

    def log(text):
        print(text, flush=True)
    ensure_server()
    before = lms_ps()
    rows = lms_ls()
    models = chat_models(rows, names)
    if not models:
        print("llm-bench: no chat model to run", file=sys.stderr)
        return 1
    old = read_results()
    write_results(dict(old, running={"started": int(time.time()), "pid": os.getpid(),
                                     "models": [a for _, a in models]}))
    bench = Bench(quick, log)
    t0 = time.time()
    try:
        runs, quality = bench.run(models)
    finally:
        restore(before, log)
    done = [a for _, a in models]
    all_runs = merge(old.get("runs") or [], runs, done)
    all_quality = {k: v for k, v in (old.get("quality") or {}).items() if k not in done} | quality
    sizes = {a: r.get("sizeBytes") or 0 for r, a in chat_models(rows)}
    used, total = smi_used()
    data = {"time": int(time.time()), "took_s": int(time.time() - t0), "quick": quick,
            "card_total": total, "before": [r.get("identifier") for r in before],
            "runs": all_runs, "quality": all_quality,
            "calculator": calculator_check(all_runs),
            "recommend": recommend(all_runs, all_quality, sizes)}
    write_results(data)
    print(show_text(data))
    return 0


def fmt(v, spec="{:.0f}", none="-"):
    return none if v is None else spec.format(v)


def table_rows(data):
    """[(model, ctx, parallel, VRAM, predicted, pp, gen, x4, TTFT, tool, note)]
    as strings, for show and the Settings page."""
    q = data.get("quality") or {}
    out = []
    for r in data.get("runs") or []:
        tool = q.get(r["alias"], {}).get("tool_ok")
        note = r.get("skipped") or r.get("error") or (("spilled: " + r.get("spill_detail", ""))
                                                      if r.get("spilled") else "")
        out.append((r["alias"], f"{r['ctx'] // 1024}k", str(r["parallel"]),
                    fmt(measured(r) / GB if r.get("vram") else None, "{:.1f}"),
                    fmt(r["predicted"]["need"] / GB if r.get("predicted") else None, "{:.1f}"),
                    fmt(r.get("pp_tps")), fmt(r.get("gen_tps"), "{:.1f}"), fmt(r.get("agg_tps")),
                    fmt(r.get("ttft_s"), "{:.2f}"), "-" if tool is None else ("yes" if tool else "no"), note))
    return out


HEAD = ("model", "ctx", "slots", "VRAM GB", "pred GB", "pp t/s", "gen t/s", "x4 t/s", "TTFT s", "tool", "")


def show_text(data):
    if not data.get("runs"):
        return "no results yet: llm-bench.py run"
    rows = [HEAD] + table_rows(data)
    widths = [max(len(r[i]) for r in rows) for i in range(len(HEAD) - 1)]
    lines = ["  ".join(c.ljust(w) for c, w in zip(r[:-1], widths)) + ("  " + r[-1] if r[-1] else "")
             for r in rows]
    q = data.get("quality") or {}
    lines.append("")
    for alias, v in sorted(q.items()):
        lines.append(f"{alias}: tool call {'ok' if v.get('tool_ok') else 'failed'}, instruction "
                     f"{'ok' if v.get('instr_ok') else 'failed'} ({v.get('instr_detail', '')!r})")
    c = data.get("calculator") or {}
    if c.get("n"):
        lines.append(f"\ncalculator: measured - predicted, mean {c['mean_gb']:+.2f} GB over {c['n']} runs; "
                     + ", ".join(f"{a} {e:+.2f}" for a, e in c["per_model"].items()))
    lines.append("")
    for role, rec in (data.get("recommend") or {}).items():
        lines.append(f"{role:8} {rec.get('model') or '(none)'}: {rec.get('why')}")
    return "\n".join(lines)


def recheck(data, predict):
    """`data` with each run's prediction worked out again by predict(key,
    ctx, parallel) (None: keep it), the calculator check and the
    recommendations redone."""
    for r in data.get("runs") or []:
        new = predict(r["key"], r["ctx"], r["parallel"]) if r.get("key") else None
        if new is not None:
            r.setdefault("predicted_before", r.get("predicted"))
            r["predicted"] = new
    data["calculator"] = calculator_check(data.get("runs") or [])
    data["recommend"] = recommend(data.get("runs") or [], data.get("quality") or {},
                                  {r["alias"]: r.get("size") or 0 for r in data.get("runs") or []})
    return data


def cmd_recheck():
    data = read_results()
    rows = {r["modelKey"]: r for r in llm_models._read_cache().get("models") or []}
    bench = Bench()

    def predict(key, ctx, par):
        return bench.predicted(rows[key], ctx, par)[0] if key in rows else None
    write_results(recheck(data, predict))
    print(show_text(data))
    return 0


def main(argv):
    cmd = argv[0] if argv else "show"
    if cmd == "recheck":
        return cmd_recheck()
    if cmd == "run":
        return cmd_run(argv[1:])
    if cmd == "show":
        data = read_results()
        print(json.dumps(data, indent=1) if "--json" in argv else show_text(data))
        return 0
    print(__doc__.split("\n\n")[1], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
