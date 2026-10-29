#!/usr/bin/env python3
"""LM Studio and the graphics card's memory: what is loaded, what would fit,
and the models put away while a game runs. Settings > AI & models runs this.

    llm-gpu.py status [--json]        the card's memory and who uses it, the
                                      loaded models, the installed ones with
                                      a "Fits?" for the context and slots in
                                      llm.json, the switches below
    llm-gpu.py unload KEY|--all       unload one loaded model (key, alias or
                                      identifier) or all of them
    llm-gpu.py load KEY [--force]     load one the way the chat window needs it
                                      (llm_models.ensure_local: the context
                                      and slots in llm.json); refused when it
                                      will not fit next to what is on the
                                      card now, unless --force
    llm-gpu.py set KEY VALUE          one of the switches below, on | off
    llm-gpu.py fit KEY CTX PARALLEL   the fit calculator for one model
    llm-gpu.py gamemode on|off        what lua/gamemode.lua runs each time
                                      gamemode turns on or off

The switches, in ~/.local/state/hypr/llm-gpu.conf (key=value lines, like
capture.conf; a missing key is its default):

    unload_for_games    on   gamemode ON unloads every LM Studio model
                             (`lms unload --all`), the list of them kept in
                             llm-gpu-unloaded.json next to it
    reload_after_games  off  gamemode OFF loads that list again; when off,
                             the list is only kept, and the Settings page
                             offers "Load again" (a 20 GB model takes RAM and
                             half a minute to come back, which a desktop just
                             out of a game may not want -- and a model is
                             loaded again anyway the next time it is asked)

Never wakes LM Studio to put it away: with neither its daemon (llmster)
nor a llama-server running -- both read from /proc -- `gamemode on`,
`unload` and `status` do not run lms at all, so gamemode costs one Python
start when LM Studio is down.

THE FIT CALCULATOR (fit() and kv_bytes(), pure, tests/test_settings_ai.py):

    needed = model size + KV cache + COMPUTE (0.5 GB) + room for others
    room for others = RESERVE (2 GB, the desktop: the compositor, a
    browser, LM Studio's own process; measured 1.9-2.9 GB with no model
    loaded, llm-bench.py 2026-10-20 -- it was 1.5, and Qwen 3.8 at 64k with
    4 slots then "fit" and failed to load) -- or, for "next to what is
    loaded now", the card's memory in use right now (when that is more)

and `needed <= total VRAM` is "fits", within TIGHT (1 GB) of it "tight",
past it "won't fit" -- LM Studio then keeps some layers in RAM (it did with
GLM 4.7 Flash here: 39 of its 48 layers on the card, even at 16k), and every
token is slow -- or, for a dense model it loads with every layer on the card
(Qwen 3.6/3.8 at 128k), the load fails outright: out of card memory.

The model size is lms ls's sizeBytes (the vision projector included), less
the tensors llama.cpp keeps in RAM whatever the offload: Gemma 4's
per-layer token embeddings (per_layer_token_embd, 2.3 GB of E4B's 5.3 GB
file -- without this the calculator said 7.1 GB where the card held 5.1,
llm-bench.py 2026-10-20). gguf_meta() sums them from the tensor table
("_host_bytes").

The KV cache, from the GGUF's own header (gguf_meta() reads only the
metadata, ~0.1 s, kept in ~/.cache/llm-gpu-gguf.json by the file's size
and mtime): llama.cpp keeps K and V in f16 (2 bytes; LM Studio's
--cache-type-k/-v f16) for every layer that has attention, so

    KV = sum over those layers of  n_kv_heads x (key_length + value_length)
         x 2 bytes x tokens kept

    tokens kept   the context (one pool shared by all slots: LM Studio runs
                  llama-server --kv-unified) -- or, on a sliding-window
                  layer (Gemma), min(context, window x slots + 512)
    the layers    block_count, less `shared_kv_layers` (Gemma 4's last
                  layers reuse earlier ones' cache); a hybrid model (Qwen
                  3.5+, `full_attention_interval` N) has attention on every
                  Nth layer only, and its other layers keep a recurrent
                  state instead: ssm.inner_size x ssm.state_size x 4 bytes
                  per layer per slot, added
    key_length    defaults to embedding_length / head_count; an MLA model
                  (DeepSeek 2, GLM 4.7 Flash) records its compressed sizes
                  (576 / 512, one KV head) and is counted the same way,
                  which errs high if llama.cpp keeps V as a view of K

Without a readable header (a model whose file is not found), a rule of
thumb: KV_PER_B (10 KiB) per token per billion parameters -- parameters from
lms ls's "27B", or for a mixture of experts ("64x2.6B") from the file's size
and its quantization's bits. It errs high for a mixture of experts.

Per slot: the context is one pool, so each of N slots is sure of only
context / N tokens (one busy slot alone can use it all). A chat with tools,
a few files and a long answer -- or a coding agent, whose own prompt is
~19k tokens -- runs out under ~24k a slot.
"""
import fcntl
import json
import os
import re
import struct
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import llm_models  # noqa: E402

HOME = os.path.expanduser("~")
STATE_DIR = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.join(HOME, ".local", "state"), "hypr")
CONF = os.path.join(STATE_DIR, "llm-gpu.conf")
UNLOADED = os.path.join(STATE_DIR, "llm-gpu-unloaded.json")
CACHE_DIR = os.environ.get("XDG_CACHE_HOME") or os.path.join(HOME, ".cache")
META_CACHE = os.path.join(CACHE_DIR, "llm-gpu-gguf.json")
LOCK = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "llm-gpu.lock")

DEFAULTS = {"unload_for_games": "on", "reload_after_games": "off"}
ON_OFF = ("on", "off")
GB = 1e9
RESERVE = 2.0 * GB          # the desktop's own use of the card (measured 1.9-2.9 GB idle)
COMPUTE = 0.5 * GB          # llama.cpp's scratch buffers on top of weights and cache
TIGHT = 1.0 * GB            # less spare than this is "tight"
KV_ELEM = 2                 # bytes: f16 K and V
SSM_ELEM = 4                # bytes: f32 recurrent state
UBATCH = 512                # llama.cpp's ubatch: a sliding-window cache keeps this many more
KV_PER_B = 10 * 1024        # bytes per token per billion parameters, the rule of thumb
LMS_DEFAULT_PARALLEL = 4    # what LM Studio loads with when not told (seen: GLM came up with 4)
AGENT_PROMPT = 19000        # tokens of a coding agent's own prompt and tools
SLOT_WARN = 24 * 1024       # a slot sure of fewer tokens than this gets a warning
VERDICT_TEXT = {"fits": "fits", "tight": "tight", "won't fit": "won't fit (would spill to RAM: slow)"}


# -- the switches ------------------------------------------------------------------
def read_conf(path=None):
    """{key: value} with the defaults filled in; a bad value is the default."""
    values = dict(DEFAULTS)
    try:
        with open(path or CONF) as handle:
            for line in handle:
                key, sep, value = line.strip().partition("=")
                if sep and key.strip() in DEFAULTS and value.strip() in ON_OFF:
                    values[key.strip()] = value.strip()
    except OSError:
        pass
    return values


def write_conf(key, value, path=None):
    if key not in DEFAULTS:
        raise ValueError(f"no setting {key!r} (there are {', '.join(DEFAULTS)})")
    if value not in ON_OFF:
        raise ValueError(f"{key} is on or off, not {value!r}")
    path = path or CONF
    values = read_conf(path)
    values[key] = value
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as handle:
        handle.write("".join(f"{k}={v}\n" for k, v in values.items()))
    os.replace(tmp, path)


# -- the GGUF header -----------------------------------------------------------------
_SCALAR = {0: "B", 1: "b", 2: "H", 3: "h", 4: "I", 5: "i", 6: "f", 7: "?", 10: "Q", 11: "q", 12: "d"}
HOST_TENSORS = re.compile(r"per_layer_token_embd\.")   # kept in RAM by llama.cpp (input tensors)
META_VERSION = 2            # in the cache's stamp: bumped when gguf_meta() keeps more
_KEEP = re.compile(r"general\.architecture$|[a-z0-9_]+\.(block_count|embedding_length|attention\.|"
                   r"full_attention_interval|ssm\.)")


def gguf_meta(path):
    """The GGUF metadata this file's KV cache needs ({key: value}, arrays of
    numbers or booleans up to 4096 long kept, the rest skipped), and
    "_host_bytes": the bytes of the tensors llama.cpp keeps in RAM
    (HOST_TENSORS, from the tensor table's offsets); None when it is not a
    GGUF. Reads only the header (the token list is skipped string by
    string, a few MB)."""
    out = {}
    with open(path, "rb") as f:
        if f.read(4) != b"GGUF":
            return None
        _version, _tensors, count = struct.unpack("<IQQ", f.read(20))

        def string():
            n, = struct.unpack("<Q", f.read(8))
            return f.read(n).decode(errors="replace")

        def value(kind, keep):
            if kind == 8:
                return string()
            if kind == 9:
                item, n = struct.unpack("<IQ", f.read(12))
                if item == 8:
                    for _ in range(n):
                        m, = struct.unpack("<Q", f.read(8))
                        f.seek(m, 1)
                    return None
                if item not in _SCALAR:
                    raise ValueError("nested GGUF array")
                width = struct.calcsize(_SCALAR[item])
                if not keep or n > 4096:
                    f.seek(width * n, 1)
                    return None
                return list(struct.unpack(f"<{n}{_SCALAR[item]}", f.read(width * n)))
            if kind not in _SCALAR:
                raise ValueError(f"GGUF value type {kind}")
            return struct.unpack("<" + _SCALAR[kind], f.read(struct.calcsize(_SCALAR[kind])))[0]

        align = 32
        for _ in range(count):
            key = string()
            kind, = struct.unpack("<I", f.read(4))
            keep = bool(_KEEP.match(key))
            v = value(kind, keep or key == "general.alignment")
            if keep:
                out[key] = v
            elif key == "general.alignment" and isinstance(v, int) and v > 0:
                align = v
        offsets = []
        for _ in range(_tensors):
            name = string()
            dims, = struct.unpack("<I", f.read(4))
            f.seek(8 * dims, 1)
            _kind, offset = struct.unpack("<IQ", f.read(12))
            offsets.append((offset, name))
        start = (f.tell() + align - 1) // align * align
        end = os.fstat(f.fileno()).st_size - start
        offsets.sort()
        host = 0
        for i, (offset, name) in enumerate(offsets):
            if HOST_TENSORS.match(name):
                host += (offsets[i + 1][0] if i + 1 < len(offsets) else end) - offset
        out["_host_bytes"] = max(0, host)
    return out


def model_file(path, root=None):
    """The .gguf on disk for lms ls's "path": "publisher/repo/file.gguf"
    as is, or for an indexed key ("qwen/qwen3.8-27b") the weights (not the
    mmproj-) file in the folder whose name starts with its last part."""
    root = root or llm_models.LMS_MODELS
    if not path:
        return None
    if path.count("/") >= 2:
        full = os.path.join(root, path)
        return full if os.path.isfile(full) else None
    want = path.split("/")[-1].lower()
    try:
        for pub in sorted(os.scandir(root), key=lambda e: e.name):
            if not pub.is_dir():
                continue
            for repo in sorted(os.scandir(pub.path), key=lambda e: e.name):
                if repo.is_dir() and repo.name.lower().startswith(want):
                    files = sorted(e.path for e in os.scandir(repo.path) if e.name.endswith(".gguf")
                                   and not e.name.lower().startswith("mmproj"))
                    if files:
                        return files[0]
    except OSError:
        pass
    return None


def meta_for(path):
    """gguf_meta() of lms ls's `path`, through the cache; None when unknown."""
    full = model_file(path)
    if not full:
        return None
    try:
        st = os.stat(full)
    except OSError:
        return None
    stamp = [st.st_size, int(st.st_mtime), META_VERSION]
    try:
        with open(META_CACHE) as handle:
            cache = json.load(handle)
    except (OSError, ValueError):
        cache = {}
    hit = cache.get(full)
    if hit and hit.get("stamp") == stamp:
        return hit.get("meta")
    try:
        meta = gguf_meta(full)
    except (OSError, ValueError, struct.error):
        meta = None
    cache[full] = {"stamp": stamp, "meta": meta}
    try:
        os.makedirs(os.path.dirname(META_CACHE), exist_ok=True)
        tmp = META_CACHE + ".tmp"
        with open(tmp, "w") as handle:
            json.dump(cache, handle)
        os.replace(tmp, META_CACHE)
    except OSError:
        pass
    return meta


# -- the calculator (pure) ----------------------------------------------------------------
def _per_layer(value, i, default=None):
    if isinstance(value, list):
        return value[i] if i < len(value) else default
    return default if value is None else value


def kv_bytes(meta, ctx, parallel=1):
    """The KV cache (and a hybrid's recurrent state) in bytes for `ctx`
    tokens over `parallel` slots, from gguf_meta(); None when the header
    lacks what it needs. The formula: the module docstring."""
    if not meta:
        return None
    arch = meta.get("general.architecture") or ""

    def get(name, default=None):
        return meta.get(f"{arch}.{name}", default)

    layers = get("block_count")
    heads = get("attention.head_count")
    kv_heads = get("attention.head_count_kv", heads)
    if not isinstance(layers, int) or layers <= 0 or kv_heads is None:
        return None
    embd = get("embedding_length")
    head = _per_layer(heads, 0)
    key_len = get("attention.key_length") or (embd // head if embd and head else None)
    if not key_len:
        return None
    val_len = get("attention.value_length") or key_len
    key_swa = get("attention.key_length_swa") or key_len
    val_swa = get("attention.value_length_swa") or val_len
    window = get("attention.sliding_window")
    pattern = get("attention.sliding_window_pattern")
    interval = get("full_attention_interval")
    own = layers - (get("attention.shared_kv_layers") or 0)
    parallel = max(1, int(parallel or 1))
    total = 0
    recurrent = 0
    for i in range(max(0, own)):
        if interval and (i + 1) % interval:
            recurrent += 1
            continue
        n_kv = _per_layer(kv_heads, i, 0) or 0
        swa = bool(window) and isinstance(pattern, list) and bool(_per_layer(pattern, i, False))
        if swa:
            tokens = min(ctx, window * parallel + UBATCH)
            total += n_kv * (key_swa + val_swa) * KV_ELEM * tokens
        else:
            total += n_kv * (key_len + val_len) * KV_ELEM * ctx
    if recurrent:
        inner, state = get("ssm.inner_size") or 0, get("ssm.state_size") or 0
        total += recurrent * inner * state * SSM_ELEM * parallel
    return total


def params_billions(params, size=0, quant=""):
    """lms ls's paramsString as billions: "27B" 27, "7.5B" 7.5, "270M"
    0.27; a mixture of experts ("64x2.6B") from the file size and the
    quantization's bits instead (Q4 counted as 4.5, the K-quants' extra);
    None when neither says."""
    m = re.fullmatch(r"\s*([\d.]+)\s*([BM])\s*", params or "", re.I)
    if m:
        return float(m.group(1)) / (1000 if m.group(2).upper() == "M" else 1)
    bits = re.search(r"(\d+)", quant or "")
    if size and bits:
        return size * 8 / (int(bits.group(1)) + 0.5) / 1e9
    return None


def rule_kv(billions, ctx):
    return None if billions is None else int(billions * KV_PER_B * ctx)


def estimate(row, ctx, parallel, meta=None):
    """(KV bytes, how it was worked out: "gguf" | "rule of thumb" | "")
    for an lms ls row (llm_models' cache: sizeBytes, paramsString, quant)."""
    kv = kv_bytes(meta, ctx, parallel)
    if kv is not None:
        return kv, "gguf"
    kv = rule_kv(params_billions(row.get("paramsString"), row.get("sizeBytes") or 0, row.get("quant")), ctx)
    return (kv, "rule of thumb") if kv is not None else (0, "")


def card_size(row, meta=None):
    """The bytes of an lms ls row's model that go on the card: sizeBytes
    less what llama.cpp keeps in RAM (gguf_meta's "_host_bytes")."""
    return max(0, (row.get("sizeBytes") or 0) - ((meta or {}).get("_host_bytes") or 0))


def fit(size, kv, total, others=RESERVE):
    """The verdict for a model of `size` bytes with `kv` bytes of cache on a
    card of `total` bytes, `others` already taken (the RESERVE, or what is
    in use now): {"verdict": "fits" | "tight" | "won't fit", "text",
    "need", "room", "spare"} -- need and room in bytes, spare = room - need."""
    need = int(size + kv + COMPUTE)
    room = int(total - max(others, 0))
    spare = room - need
    verdict = "won't fit" if spare < 0 else "tight" if spare < TIGHT else "fits"
    return {"verdict": verdict, "text": VERDICT_TEXT[verdict], "need": need, "room": room, "spare": spare}


def per_slot(ctx, parallel):
    return ctx // max(1, parallel or LMS_DEFAULT_PARALLEL)


def slot_warning(ctx, parallel):
    """A line for the page when a slot is sure of too little, else ""."""
    slot = per_slot(ctx, parallel)
    if slot >= SLOT_WARN:
        return ""
    return (f"each slot is sure of only {slot // 1024}k tokens, and a chat with tools and files (a coding "
            f"agent's own prompt alone is ~{AGENT_PROMPT // 1000}k) runs out, the sooner with several at once. More context or "
            "fewer slots")


def ttl_left(row, now_ms):
    """Seconds before LM Studio unloads an idle model, from lms ps's ttlMs and
    lastUsedTime (ms); None without a TTL."""
    ttl = row.get("ttlMs")
    if not ttl:
        return None
    last = row.get("lastUsedTime") or now_ms
    return max(0, int((ttl - (now_ms - last)) / 1000))


def gb(n):
    return f"{(n or 0) / GB:.1f} GB"


# -- the machine ----------------------------------------------------------------------
def servers():
    """[{pid, model (the .gguf path), ctx}] for every llama-server LM Studio
    runs (one per loaded model), from /proc."""
    out = []
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/comm") as handle:
                if handle.read().strip() != "llama-server":
                    continue
            with open(f"/proc/{pid}/cmdline", "rb") as handle:
                argv = handle.read().decode(errors="replace").split("\0")
        except OSError:
            continue

        def arg(flag):
            return argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else None
        ctx = arg("--ctx-size")
        out.append({"pid": int(pid), "model": arg("--model") or "",
                    "ctx": int(ctx) if ctx and ctx.isdigit() else None})
    return out


def running():
    """Is any of LM Studio up (without asking lms, which would wake it)?"""
    return bool(servers()) or llm_models._daemon_running()


def parse_smi(gpu_csv, apps_csv):
    """nvidia-smi's CSV (no header, no units) -> {name, total, used, procs:
    [{pid, name, used}]}, bytes; None without a card. gpu() no longer runs
    nvidia-smi (card_info below is its shape from gpu.py); this stays for
    a CSV pasted by hand and its tests."""
    first = (gpu_csv or "").strip().splitlines()
    if not first:
        return None
    parts = [p.strip() for p in first[0].split(",")]
    try:
        name, used, total = parts[0], int(parts[1]) * 2**20, int(parts[2]) * 2**20
    except (IndexError, ValueError):
        return None
    procs = []
    for line in (apps_csv or "").strip().splitlines():
        bits = [b.strip() for b in line.split(",")]
        if len(bits) < 3:
            continue
        try:
            pid, mem = int(bits[0]), int(bits[-1]) * 2**20
        except ValueError:
            continue
        procs.append({"pid": pid, "name": os.path.basename(",".join(bits[1:-1]).split(" ")[0]), "used": mem})
    procs.sort(key=lambda p: -p["used"])
    return {"name": name, "total": total, "used": used, "procs": procs}


def card_info(card, procs, names=None):
    """A gpu.py card and its {pid: MiB} -> the same shape as parse_smi ({name,
    vendor, total, used, procs: [{pid, name, used}]}, bytes); None for no
    card or one that does not report its memory (an iGPU shares the RAM:
    there is no card memory to fit a model into, and the calculator says ?;
    so does an APU's small carve-out of the RAM: discrete False)."""
    if (not card or not card.get("discrete", True) or not card.get("vram_total")
            or card.get("vram_used") is None):
        return None
    names = names or {}
    rows = [{"pid": pid, "name": names.get(pid) or f"pid {pid}", "used": mib * 2**20}
            for pid, mib in procs.items()]
    rows.sort(key=lambda p: -p["used"])
    return {"name": card["name"], "vendor": card.get("vendor"), "total": card["vram_total"] * 2**20,
            "used": card["vram_used"] * 2**20, "procs": rows}


def gpu():
    """The main graphics card, whoever made it, from gpu.py (in-process: NVML
    on NVIDIA, sysfs and fdinfo on AMD / Intel; nothing forked). Processes:
    the compute ones (a model server is one): NVIDIA's compute list, AMD's
    ROCm clients; none on Intel, which cannot tell them from graphics."""
    try:
        import gpu as cards
        card = cards.primary()
        procs = cards.processes(card, compute_only=True) if card else {}
    except Exception:  # noqa: BLE001  (no card numbers, never a broken page)
        return None
    names = {}
    for pid in procs:
        try:
            with open(f"/proc/{pid}/comm") as handle:
                names[pid] = handle.read().strip()
        except OSError:
            pass
    return card_info(card, procs, names)


def lms_ps():
    """lms ps --json, only while LM Studio is up; [] otherwise."""
    if not running():
        return []
    try:
        out = subprocess.run([llm_models.LMS, "ps", "--json"], capture_output=True, text=True,
                             timeout=30).stdout
        rows = llm_models._json_out(out) or []
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    return [r for r in rows if isinstance(r, dict) and r.get("modelKey")]


def installed_rows():
    """llm_models' cache of lms ls (it is refreshed by `llm_models.py
    refresh`; a model deleted since drops out there)."""
    return llm_models._read_cache().get("models") or []


def alias_map(rows):
    return llm_models._aliases([r["modelKey"] for r in rows if r.get("modelKey")])


def read_unloaded():
    try:
        with open(UNLOADED) as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) and data.get("models") else None
    except (OSError, ValueError):
        return None


def write_unloaded(data):
    os.makedirs(os.path.dirname(UNLOADED), exist_ok=True)
    if data is None:
        try:
            os.remove(UNLOADED)
        except OSError:
            pass
        return
    tmp = UNLOADED + ".tmp"
    with open(tmp, "w") as handle:
        json.dump(data, handle, indent=1)
    os.replace(tmp, UNLOADED)


def status():
    ctx, parallel = llm_models.local_options()
    card = gpu()
    loaded = lms_ps()
    rows = installed_rows()
    known = {r["modelKey"]: r for r in rows}
    aliases = alias_map(rows + [r for r in loaded if r["modelKey"] not in known])
    now_ms = time.time() * 1000
    procs = servers()
    by_pid = {p["pid"]: p for p in procs}
    file_to_key = {}
    for r in rows:
        f = model_file(r.get("path"))
        if f:
            file_to_key[f] = r["modelKey"]
    if card:
        for p in card["procs"]:
            if p["pid"] in by_pid:
                key = file_to_key.get(by_pid[p["pid"]]["model"])
                p["name"] = "LM Studio: " + (aliases.get(key) or os.path.basename(by_pid[p["pid"]]["model"]))
                p["lmstudio"] = True
    total = card["total"] if card else 0
    loaded_out = []
    for r in loaded:
        loaded_out.append({"key": r["modelKey"], "alias": aliases.get(r["modelKey"], r["modelKey"]),
                           "identifier": r.get("identifier") or r["modelKey"], "size": r.get("sizeBytes") or 0,
                           "context": r.get("contextLength"), "parallel": r.get("parallel"),
                           "status": r.get("status") or "", "ttl_left": ttl_left(r, now_ms)})
    loaded_keys = {r["key"] for r in loaded_out}
    installed = []
    for r in rows:
        meta = meta_for(r.get("path"))
        kv, how = estimate(r, ctx, parallel or LMS_DEFAULT_PARALLEL, meta)
        verdict = fit(card_size(r, meta), kv, total) if total else None
        installed.append({"key": r["modelKey"], "alias": aliases.get(r["modelKey"], r["modelKey"]),
                          "label": r.get("displayName") or r["modelKey"], "size": r.get("sizeBytes") or 0,
                          "params": r.get("paramsString") or "", "quant": r.get("quant") or "",
                          "tools": bool(r.get("trainedForToolUse")), "max_context": r.get("maxContextLength"),
                          "kv": kv, "kv_how": how, "fit": verdict, "loaded": r["modelKey"] in loaded_keys})
    installed.sort(key=lambda m: m["alias"])
    return {"running": running(), "gpu": card, "loaded": loaded_out, "installed": installed,
            "context": ctx, "parallel": parallel, "default_parallel": LMS_DEFAULT_PARALLEL,
            "per_slot": per_slot(ctx, parallel), "slot_warning": slot_warning(ctx, parallel),
            "settings": read_conf(), "unloaded": read_unloaded(), "stale": llm_models.stale(),
            "roles": {k: llm_models.settings()[k] for k in llm_models.ROLES}}


def fit_now(model, ctx=None, parallel=None):
    """fit() for `model` (a local llm_models.Model) next to whatever is on
    the card right now; None when there is no card to ask, or it is loaded
    already (nothing more would go on the card)."""
    card = gpu()
    if not card:
        return None
    row = next((r for r in installed_rows() if r["modelKey"] == model.ident), {"sizeBytes": 0})
    weights = model_file(row.get("path") or model.path)
    if weights and any(s["model"] == weights for s in servers()):
        return None
    dctx, dpar = llm_models.local_options()
    ctx, parallel = ctx or dctx, parallel or dpar or LMS_DEFAULT_PARALLEL
    meta = meta_for(row.get("path") or model.path)
    kv, _how = estimate(row, ctx, parallel, meta)
    return fit(card_size(row, meta), kv, card["total"], max(card["used"], RESERVE))


# -- the commands -------------------------------------------------------------------------
def _lock():
    os.makedirs(os.path.dirname(LOCK), exist_ok=True)
    handle = open(LOCK, "a")
    fcntl.flock(handle, fcntl.LOCK_EX)
    return handle


def _lms(*args, timeout=60):
    return subprocess.run([llm_models.LMS, *args], capture_output=True, text=True, timeout=timeout)


def find_loaded(word, loaded):
    w = word.lower()
    rows = installed_rows()
    aliases = alias_map(rows + loaded)
    model = llm_models.resolve(word)
    for r in loaded:
        if w in ((r.get("identifier") or "").lower(), r["modelKey"].lower(),
                 aliases.get(r["modelKey"], "").lower()) or (model and model.ident == r["modelKey"]):
            return r
    return None


def unload(word):
    if not running():
        return "nothing is loaded (LM Studio is not running)"
    if word == "--all":
        r = _lms("unload", "--all")
        if r.returncode:
            raise RuntimeError("lms unload --all failed: " + (r.stderr or r.stdout).strip()[-200:])
        return "unloaded every model"
    loaded = lms_ps()
    row = find_loaded(word, loaded)
    if row is None:
        raise RuntimeError(f"{word} is not loaded")
    r = _lms("unload", row.get("identifier") or row["modelKey"])
    if r.returncode:
        raise RuntimeError("lms unload failed: " + (r.stderr or r.stdout).strip()[-200:])
    return f"unloaded {word}"


def load(word, force=False):
    model = llm_models.resolve(word)
    if model is None or not model.local:
        raise RuntimeError(f"no local model {word!r}")
    verdict = fit_now(model)
    if verdict and verdict["verdict"] == "won't fit" and not force:
        raise RuntimeError(f"{model.name} needs {gb(verdict['need'])} and the card has {gb(verdict['room'])} "
                           "free: it would spill to RAM (slow). Unload something first, or load anyway")
    ok, why = llm_models.ensure_local(model)
    if not ok:
        raise RuntimeError(why)
    left = read_unloaded()
    if left:
        left["models"] = [m for m in left["models"] if m.get("modelKey") != model.ident]
        write_unloaded(left if left["models"] else None)
    return f"loaded {model.name}"


def gamemode(state):
    """lua/gamemode.lua's hook. Returns what it did, for the log line."""
    with _lock():
        if state == "on":
            if read_conf()["unload_for_games"] != "on":
                return "unload_for_games is off"
            if not running():
                return "LM Studio is not running"
            loaded = lms_ps()
            if not loaded:
                return "nothing loaded"
            write_unloaded({"time": int(time.time()), "game_over": None, "models": [
                {k: r.get(k) for k in ("modelKey", "identifier", "contextLength", "parallel", "ttlMs")}
                for r in loaded]})
            _lms("unload", "--all")
            return "unloaded " + ", ".join(r["modelKey"] for r in loaded)
        left = read_unloaded()
        if not left:
            return "nothing was unloaded"
        if read_conf()["reload_after_games"] != "on":
            left["game_over"] = int(time.time())
            write_unloaded(left)
            return "kept the list (reload_after_games is off)"
        done = []
        for m in left["models"]:
            model = llm_models.resolve(m["modelKey"], prefix=False)
            if model is None:
                continue        # deleted since
            ok, _why = llm_models.ensure_local(model)
            if ok:
                done.append(model.name)
        write_unloaded(None)
        return "loaded again: " + (", ".join(done) or "none")


def main(argv):
    cmd = argv[0] if argv else "status"
    try:
        if cmd == "status":
            data = status()
            if "--json" in argv:
                print(json.dumps(data, indent=1))
                return 0
            card = data["gpu"]
            if card:
                print(f"{card['name']}: {gb(card['used'])} of {gb(card['total'])} used")
                for p in card["procs"]:
                    print(f"  {gb(p['used']):>8}  {p['name']}")
            print("loaded:", ", ".join(f"{r['alias']} ({r['context']} ctx, {r['parallel']} slots)"
                                       for r in data["loaded"]) or "none")
            for m in data["installed"]:
                fitness = m["fit"]["text"] if m["fit"] else "?"
                print(f"  {m['alias']:24} {gb(m['size']):>8}  KV {gb(m['kv'])} ({m['kv_how']})  {fitness}")
            print(f"context {data['context']}, slots {data['parallel'] or 'LM Studio default'}, "
                  f"{data['per_slot']} per slot")
            print("settings:", data["settings"])
            return 0
        if cmd == "unload" and len(argv) > 1:
            print(unload(argv[1]))
            return 0
        if cmd == "load" and len(argv) > 1:
            print(load(argv[1], "--force" in argv))
            return 0
        if cmd == "set" and len(argv) == 3:
            write_conf(argv[1], argv[2])
            return 0
        if cmd == "fit" and len(argv) == 4:
            model = llm_models.resolve(argv[1])
            if model is None or not model.local:
                raise RuntimeError(f"no local model {argv[1]!r}")
            ctx, parallel = int(argv[2]), int(argv[3])
            row = next((r for r in installed_rows() if r["modelKey"] == model.ident), {})
            meta = meta_for(row.get("path") or model.path)
            kv, how = estimate(row, ctx, parallel, meta)
            card = gpu()
            out = {"model": model.name, "size": row.get("sizeBytes") or 0, "kv": kv, "kv_how": how,
                   "per_slot": per_slot(ctx, parallel), "slot_warning": slot_warning(ctx, parallel),
                   "fit": fit(card_size(row, meta), kv, card["total"]) if card else None,
                   "fit_now": fit_now(model, ctx, parallel)}
            print(json.dumps(out, indent=1))
            return 0
        if cmd == "gamemode" and argv[1:2] in (["on"], ["off"]):
            print(gamemode(argv[1]))
            return 0
    except (RuntimeError, ValueError) as exc:
        print(f"llm-gpu: {exc}", file=sys.stderr)
        return 1
    print(__doc__.split("\n\n")[1], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
