#!/usr/bin/env python3
"""Hugging Face's GGUF models, for the launcher's ?get and the LLM chat
window's model manager (llm_manager.py): the search, a repo's variants and
their sizes, how one fits this machine; and the models already on disk,
with a way to delete one. The download itself is llm_models.get (lms get).

    hf_search(query)      the GGUF repos for some words, most downloaded
                          first, LM Studio's own lmstudio-community
                          quantizations raised (two requests side by side),
                          then the file sizes of the top HF_SIZED; kept per
                          query for the session in HF_CACHE
    variants(repo)        every quantization the repo has, its size and fit
    fit(size)             "fits GPU" / "partial offload" / "too big"
    on_disk()             ~/.lmstudio/models, one entry per author/repo
                          folder, with the lms ls models in it (none: an
                          unfinished download or a lone mmproj)
    remove(folder)        delete one (refused while it downloads or one of
                          its models is loaded)

Hugging Face's public API, no key, no account: nothing is sent but the
words searched and the repo names looked at. Every call that asks it or
walks the disk blocks: run it in a thread.

    llm_hub.py search WORDS ...     the search, as text
    llm_hub.py variants REPO        a repo's variants
    llm_hub.py disk                 what is on disk

No GTK here: the launcher imports this on every start.
"""

import json
import os
import re
import shutil
import sys
import threading
import urllib.parse
import urllib.request

import llm_models

HF_API = "https://huggingface.co/api/models"
HF_LIMIT = 24               # repos asked for
HF_PICKS = 6                # lmstudio-community repos asked for, alongside
HF_SIZED = 6                # top repos whose file sizes are asked (one request each)
HF_EXPAND = ("downloads", "likes", "lastModified", "tags", "gguf", "siblings")
HF_CACHE = {}               # query -> {"rows": [...], "error": str} (rows: dicts, ranked)
TREES = {}                  # repo -> its file tree, asked once a session
DISK_SPARE = 10e9           # bytes left free after a download, or Enter asks first
# The variant downloaded: the first of these the repo has (Q4_K_M: the usual
# best size for the quality), and its bits per weight, to guess a size
# before the real one is in.
QUANTS = (("Q4_K_M", 4.85), ("Q4_K_S", 4.6), ("IQ4_XS", 4.3), ("Q4_0", 4.55), ("Q5_K_M", 5.7),
          ("Q5_K_S", 5.55), ("Q6_K", 6.6), ("Q8_0", 8.5), ("Q3_K_L", 4.3), ("Q3_K_M", 3.9),
          ("IQ3_M", 3.7), ("Q2_K", 3.0), ("BF16", 16.0), ("F16", 16.0))
QUANT_RE = re.compile(r"(?:^|[-_.])(I?Q\d(?:_[A-Z0-9]{1,2})+|BF16|F16|F32)(?=$|[-_.])", re.I)
_HW = {}                    # "vram", "ram": bytes, asked once (in the search thread)


def ram_bytes():
    """MemTotal from /proc/meminfo, in bytes (32 GB if it cannot be read)."""
    try:
        with open("/proc/meminfo") as handle:
            return int(handle.readline().split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return 32e9


def vram_bytes(card, ram):
    """The memory a model can be loaded into on the GPU, from gpu.py's
    primary() card: its vram_total (MiB); no card, or an integrated one
    (vram_total None, or an AMD APU's small carve-out with discrete False:
    it shares the RAM) -> the RAM itself."""
    card = card or {}
    total = card.get("vram_total")
    return total * 1024 ** 2 if total and card.get("discrete") is not False else ram


def hardware():
    """{"vram", "ram"} in bytes: gpu.py's main card (any maker; in-process,
    nothing forked), /proc/meminfo. Blocking once (~50 ms): the search thread."""
    if not _HW:
        ram = ram_bytes()
        try:
            import gpu
            card = gpu.primary()
        except Exception:  # noqa: BLE001 -- no card info is the no-card answer
            card = None
        _HW.update(vram=vram_bytes(card, ram), ram=ram)
    return _HW


def quant_of(path):
    """"Q4_K_M" for ".../Model-Q4_K_M-00001-of-00002.gguf", None for a file
    that is no model's weights (mmproj, imatrix) or names no quantization."""
    base = os.path.basename(path)
    if not base.lower().endswith(".gguf") or re.search(r"mmproj|imatrix", base, re.I):
        return None
    hits = QUANT_RE.findall(split_base(base))
    return hits[-1].upper() if hits else None


def split_base(path):
    """A file's name without .gguf and a split's "-00001-of-00003": one
    name for all the parts of one file."""
    return re.sub(r"-\d{5}-of-\d{5}$", "", os.path.basename(path)[:-5])


def hf_get(url, timeout=8):
    req = urllib.request.Request(url, headers={"User-Agent": "llm_hub.py (Atrium desktop)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def hf_row(repo):
    """One search answer, cut down to what an item needs."""
    files = [s.get("rfilename", "") for s in repo.get("siblings") or []]
    quants = {q for q in map(quant_of, files) if q}
    variant = next((q for q, _ in QUANTS if q in quants), None)
    params = (repo.get("gguf") or {}).get("total") or 0
    if not params:              # "Qwen2.5-7B-Instruct-GGUF": the name's own count
        hit = re.search(r"(?:^|[-_])(\d+(?:\.\d+)?)[Bb](?:[-_]|$)", repo["id"].split("/")[-1])
        params = float(hit.group(1)) * 1e9 if hit else 0
    bpw = dict(QUANTS).get(variant)
    return {"id": repo["id"], "downloads": repo.get("downloads") or 0, "likes": repo.get("likes") or 0,
            "modified": repo.get("lastModified") or "", "params": params, "variant": variant,
            "guess": params * bpw / 8 if params and bpw else 0, "size": 0,
            "moe": (re.search(r"[-_](A\d+(?:\.\d+)?B)(?:[-_]|$)", repo["id"], re.I) or [None, None])[1],
            "pick": repo["id"].lower().startswith("lmstudio-community/"),
            "gguf": any(f.lower().endswith(".gguf") for f in files)}


def hf_rank(rows):
    """Most downloaded first, a lmstudio-community repo counted as eight
    times its downloads (LM Studio's own, tested quantizations of the
    model), repos without a .gguf file or a known variant last."""
    def weight(row):
        return row["downloads"] * (8 if row["pick"] else 1) * (1 if row["gguf"] else 0.01) \
            * (1 if row["variant"] else 0.2)
    return sorted(rows, key=weight, reverse=True)


def hf_search(query, on_update=lambda: None):
    """Ask Hugging Face for `query` and fill HF_CACHE[query]; then the file
    sizes of the top HF_SIZED (in parallel), on_update() after each phase.
    Blocking (~0.2 s + ~0.2 s): a thread. Two requests for the search --
    the most downloaded GGUF repos, and lmstudio-community's -- side by side."""
    expand = "".join(f"&expand[]={e}" for e in HF_EXPAND)
    base = f"{HF_API}?search={urllib.parse.quote(query)}&filter=gguf&sort=downloads{expand}"
    answers, errors = {}, []

    def ask(key, url):
        try:
            answers[key] = hf_get(url)
        except (OSError, ValueError) as exc:
            errors.append(str(getattr(exc, "reason", exc)))

    threads = [threading.Thread(target=ask, args=("all", f"{base}&limit={HF_LIMIT}")),
               threading.Thread(target=ask, args=("picks", f"{base}&limit={HF_PICKS}&author=lmstudio-community"))]
    for t in threads:
        t.start()
    hardware()
    for t in threads:
        t.join()
    if "all" not in answers:
        HF_CACHE[query] = {"rows": [], "error": errors[0] if errors else "no answer"}
        on_update()
        return HF_CACHE[query]
    seen, rows = set(), []
    for repo in answers.get("picks", []) + answers["all"]:
        if isinstance(repo, dict) and repo.get("id") and repo["id"] not in seen:
            seen.add(repo["id"])
            rows.append(hf_row(repo))
    entry = HF_CACHE[query] = {"rows": hf_rank(rows), "error": ""}
    on_update()

    def size(row):
        try:
            row["size"] = variant_sizes(repo_tree(row["id"])).get(row["variant"], 0)
        except (OSError, ValueError):
            pass
    threads = [threading.Thread(target=size, args=(row,)) for row in entry["rows"][:HF_SIZED]
               if row["variant"]]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if threads:
        on_update()
    return entry


def gb(n):
    return f"{n / 1e9:.1f} GB" if n >= 1e9 else f"{n / 1e6:.0f} MB"


def count(n):
    for size, unit in ((1e6, "M"), (1e3, "k")):
        if n >= size:
            return f"{n / size:.1f}".rstrip("0").rstrip(".") + unit
    return str(n)


def fit(size):
    """vs this machine: the weights plus ~1.5 GB of context in VRAM, or
    split with system RAM (half of it), or not at all."""
    if not _HW:
        ram = ram_bytes()
    hw = _HW or {"vram": ram, "ram": ram}      # before hardware() has run: as if no card
    if size + 1.5e9 <= hw["vram"]:
        return "fits GPU"
    if size <= hw["vram"] + hw["ram"] / 2:
        return "partial offload"
    return "too big"


# -- one repo's variants: the manager's "Choose a variant" ----------------------
def variant_sizes(tree):
    """{variant: bytes} from a repo's file tree (HF's /tree/main?recursive):
    each variant's weights -- one file, or the parts of a split one, summed;
    a repo holding two of one variant (with / without MTP, single / split)
    counts the biggest, so disk and VRAM err safe."""
    sets = {}
    for f in tree if isinstance(tree, list) else []:
        if not (isinstance(f, dict) and f.get("type") == "file"):
            continue
        quant = quant_of(f.get("path", ""))
        if not quant:
            continue
        key = os.path.dirname(f["path"]) + "/" + split_base(f["path"]) \
            + ("#split" if re.search(r"-\d{5}-of-\d{5}\.gguf$", f["path"]) else "")
        per = sets.setdefault(quant, {})
        per[key] = per.get(key, 0) + (f.get("size") or 0)
    return {q: max(per.values(), default=0) for q, per in sets.items()}


def repo_tree(repo):
    """The repo's file tree, asked once a session (TREES). Blocking: a thread."""
    if repo not in TREES:
        TREES[repo] = hf_get(f"{HF_API}/{repo}/tree/main?recursive=true")
    return TREES[repo]


def variants(repo):
    """[{"variant", "size", "fit", "best"}] for `repo`, smallest first; "best"
    is the one a plain download takes (the first of QUANTS it has).
    Blocking (one request, then cached): a thread. OSError / ValueError
    when Hugging Face does not answer."""
    hardware()
    sizes = variant_sizes(repo_tree(repo))
    best = next((q for q, _ in QUANTS if q in sizes), None)
    return [{"variant": q, "size": s, "fit": fit(s) if s else "", "best": q == best}
            for q, s in sorted(sizes.items(), key=lambda kv: (kv[1], kv[0]))]


def disk_free():
    """Bytes free where LM Studio keeps its models (inf when unknown)."""
    try:
        return shutil.disk_usage(llm_models.LMS_MODELS if os.path.isdir(llm_models.LMS_MODELS)
                                 else os.path.expanduser("~")).free
    except OSError:
        return float("inf")


# -- what is on disk: the manager's "On this PC" ---------------------------------
def _folder_size(path):
    total, files, partial = 0, [], False
    for root, _dirs, names in os.walk(path):
        for name in names:
            full = os.path.join(root, name)
            try:
                total += os.lstat(full).st_size
            except OSError:
                continue
            files.append(os.path.relpath(full, path))
            partial = partial or name.endswith(".part")
    return total, sorted(files), partial


def on_disk(models=None):
    """[{"folder": "author/repo", "path", "size", "files", "partial",
    "models": [Model]}] for every model folder under ~/.lmstudio/models,
    biggest first. A folder's models are lms ls's (cached) whose path is in
    it, or -- LM Studio's indexed keys ("qwen/qwen3.8-27b") --
    llm_models.model_for_repo's guess. A folder with none is a download
    that never finished or left only its vision projector (mmproj): space
    to give back. Blocking (a walk of the folders): a thread."""
    models = [m for m in (llm_models.local_models() if models is None else models) if m.local]
    out = []
    for entry in llm_models._stamp():
        folder = entry[0]
        if "/" not in folder:
            continue
        path = os.path.join(llm_models.LMS_MODELS, folder)
        size, files, partial = _folder_size(path)
        low = folder.lower() + "/"
        mine = [m for m in models if m.path.lower().startswith(low)]
        if not mine:
            guess = llm_models.model_for_repo(folder, models)
            mine = [guess] if guess is not None else []
        out.append({"folder": folder, "path": path, "size": size, "files": files,
                    "partial": partial, "models": mine})
    out.sort(key=lambda e: e["size"], reverse=True)
    return out


def check_removable(folder, loaded=()):
    """The absolute folder to delete for `folder` ("author/repo"), or
    ValueError saying why not: a name that is not exactly one folder two
    levels under ~/.lmstudio/models, a download of it still going, or one
    of its models loaded in LM Studio now (`loaded`: modelKeys)."""
    parts = folder.split("/")
    if len(parts) != 2 or any(p in ("", ".", "..") for p in parts):
        raise ValueError(f"not a model folder: {folder}")
    root = os.path.realpath(llm_models.LMS_MODELS)
    path = os.path.realpath(os.path.join(root, folder))
    if os.path.dirname(os.path.dirname(path)) != root or not os.path.isdir(path):
        raise ValueError(f"not a model folder: {folder}")
    if llm_models.downloading(folder):
        raise ValueError(f"{folder} is still downloading: cancel it first")
    entry = next((e for e in on_disk() if e["folder"] == folder), None)
    busy = [m.name for m in (entry["models"] if entry else []) if m.ident in set(loaded)]
    if busy:
        raise ValueError(f"{', '.join(busy)} is loaded now: unload it first")
    return path


def remove(folder, loaded=()):
    """Delete a model folder for good (check_removable first), its author's
    folder too when that is left empty, then lms ls again so every list
    (the chat's picker, ?models) drops it. The bytes freed. Blocking: a thread."""
    path = check_removable(folder, loaded)
    size = _folder_size(path)[0]
    shutil.rmtree(path)
    try:
        os.rmdir(os.path.dirname(path))     # only when empty
    except OSError:
        pass
    llm_models.refresh()
    return size


if __name__ == "__main__":
    cmd, args = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ("disk", [])
    if cmd == "search" and args:
        entry = hf_search(" ".join(args))
        if entry["error"]:
            sys.exit(f"llm_hub: {entry['error']}")
        for row in entry["rows"]:
            size = row["size"] or row["guess"]
            print(f"{row['id']:60} {row['variant'] or '-':8} {gb(size) if size else '':>9}  "
                  f"{fit(size) if size else '':16} {count(row['downloads'])} downloads")
    elif cmd == "variants" and len(args) == 1:
        for v in variants(args[0]):
            print(f"{v['variant']:8} {gb(v['size']):>9}  {v['fit']:16} {'(the default)' if v['best'] else ''}")
    elif cmd == "disk":
        for e in on_disk():
            names = ", ".join(m.name for m in e["models"]) or "(no model: " + (
                "unfinished download)" if e["partial"] else "nothing lms can load)")
            print(f"{e['folder']:70} {gb(e['size']):>9}  {names}")
        print(f"free: {gb(disk_free())}")
    else:
        sys.exit(__doc__)
