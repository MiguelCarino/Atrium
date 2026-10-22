#!/usr/bin/env python3
"""The models the desktop's AI features can ask, for the launcher, the LLM
chat window (llm-chat.py) and the rest.

Kinds:

    local    LM Studio's, from `lms ls --json`, asked over LM Studio's own
             OpenAI-compatible server (http://localhost:<port>/v1; the
             chat window's engine, llm_chat_engine.py, the assistant, the
             worker...). ensure_local() readies one first.
    server   one more OpenAI-compatible server (Ollama, llama.cpp's
             llama-server, vLLM, a remote provider): its base URL in
             llm.json "server_url", an optional API key in "server_key"
             ($LLM_SERVER_KEY wins). Its models are what its GET /models
             lists -- asked over the network, so not in this registry:
             a name "server:<id>" stands for one (resolve() makes it).
    claude   Anthropic's, through the Claude Code CLI -- OPTIONAL: offered
             only when `claude` is installed (claude_cli(): on $PATH or in
             ~/.local/bin; $HYPR_CLAUDE_CLI, if set, is the one to use, or
             "none" for none). "default" (no --model: whatever Claude Code
             picks itself), fable, opus, sonnet, haiku (the CLI's aliases
             for the latest of each), or a full id typed as is
             ("claude-opus-5-5"). Without the CLI they are not in
             all_models(), resolve() does not know them, and a setting that
             names one falls back to the first local model (chosen_note()
             says so).

Each local model gets a short alias from its key: the publisher dropped, the
first three dash-separated parts kept ("qwen/qwen3.8-27b" -> "qwen3.8-27b",
"glm-4.7-flash-uncensored-..." -> "glm-4.7-flash"), longer only where two
would clash. resolve() takes an alias, a key, or (local only, 3 letters or
more) the start of one alias when no other starts the same way: "gemma" is
gemma-4-e4b, "qwen3" is nothing while there are two Qwen3s.

`lms ls` is a node CLI that may first wake LM Studio's daemon (~1-9 s), so
its answer is kept in ~/.cache/llm-models.json with a stamp of the model
folders' mtimes (~/.lmstudio/models/<publisher>/<model>): local_models()
reads that, and is stale() when a model was added or removed. refresh() runs
lms again -- never on a GTK thread; the launcher does it in a thread. Kept
per model: its key, name, size, context, quantization, whether it was
trained for tool use and whether it has vision (Model.vision).

Settings: ~/.local/state/hypr/llm.json, {"default": NAME, "quick": NAME,
"worker": NAME, "context": N, "parallel": N, "server_url": URL,
"server_key": KEY} -- the model for "?" asks and the chat window, for the
launcher's "??" quick answers, and for a local worker tool (llm-worker.py,
an MCP server a coding agent calls) ("default", "haiku" and "default" when
unset: Claude's names, so without the claude CLI the first local model);
the context (LOCAL_CONTEXT when unset) and the slots (LM Studio's own
default, 4, when unset) ensure_local loads a model with, and the extra
server -- Settings > AI & models sets them (`llm_models.py set`).
$LLM_CHAT_MODEL, if set, overrides "default" in the chat window. The same
file has LM Studio's limits -- ram_limit_gb, cpu_limit_pct,
llm_low_priority -- which llm-limits.py checks, writes into
lmstudio.service's drop-in and applies (`llm_models.py set` hands them on).

ensure_local() also makes room the other way: a model that would not fit
next to what is loaded first unloads the idle models smaller than itself
(so a quick-answer model left loaded gives way to the chat's big one).

quick_choice() is what ?? asks with when no model was typed: the "quick"
model, unless that is a local one that would not fit on the card next to
what is loaded now (or gamemode is on): then haiku, and why -- when the
claude CLI is there; without it the local model is used as it is. Falling
back is the cheaper safe choice -- the other, unloading the idle big model
to make room, costs that model half a minute and ~20 GB of RAM to come back
the next time the chat asks it, and two sessions would take turns throwing
each other off the card.

ensure_local(model, status) gets a local model ready before it is asked:
LM Studio's daemon started inside its limits (lmstudio.service, through
llm-limits.py; one already running outside them is used as it is, and the
status says so), its server up (`lms server start`), the endpoint checked to
really speak the OpenAI API (GET /v1/models), and the model loaded with
llm.json's context (LM Studio's default is 8192, too small for a chat with
tools and files) -- `lms load KEY -y -c CONTEXT --ttl LOCAL_TTL [--parallel
N]` (local_options()), so an idle model unloads itself. One already loaded
with at least that context is used as it is, whatever its slots. A load the
unit's RAM limit ended (memory.events' oom_kill went up) says so, and where
to raise it. `status` gets lines to show ("loading gemma-4-e4b… 42 %").
Blocking: run it in a thread.

    llm_models.py                  the models and the settings, listed
    llm_models.py refresh          `lms ls` again first
    llm_models.py set KEY VALUE    a setting: default | quick | worker NAME
                                   (an alias, key, server:ID or Claude name),
                                   context N (tokens), parallel N | auto,
                                   server_url URL | none, server_key KEY |
                                   none; and ram_limit_gb N, cpu_limit_pct N,
                                   llm_low_priority on|off (llm-limits.py)
    llm_models.py get REPO [VARIANT]
                                   download a Hugging Face GGUF repo with
                                   lms get, progress as a notification (the
                                   launcher's ?get; see get() below)
    llm_models.py select REPO      the same with lms's own variant picker,
                                   in a terminal (?get's Shift+Enter)

No GTK here: the launcher imports this on every start.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
LMS = os.path.join(HOME, ".lmstudio", "bin", "lms")
LMS_MODELS = os.path.join(HOME, ".lmstudio", "models")
CACHE = os.path.join(HOME, ".cache", "llm-models.json")
SETTINGS = os.path.join(HOME, ".local", "state", "hypr", "llm.json")
DEFAULTS = {"default": "default", "quick": "haiku", "worker": "default"}
ROLES = ("default", "quick", "worker")
LOCAL_CONTEXT = 32768       # tokens: a chat with tools and a few files in it
CONTEXT_RANGE = (8192, 262144)
PARALLEL_RANGE = (1, 8)
LOCAL_TTL = 1800            # s idle before LM Studio unloads the model
MIN_PREFIX = 3              # letters before a prefix picks a local model
SERVER_KEYS = ("server_url", "server_key")


class Model:
    """One choice. `name` is what is typed and stored, `label` what is shown,
    `ident` what goes to --model (None: no --model)."""

    def __init__(self, name, label, kind, ident, detail="", path="", vision=None):
        self.name, self.label, self.kind, self.ident, self.detail = name, label, kind, ident, detail
        self.path = path        # local: lms ls's "path" (publisher/repo/file.gguf, or an indexed key)
        self.vision = vision    # local: lms ls's "vision" (True / False); None: not known

    @property
    def local(self):
        return self.kind == "local"

    @property
    def claude(self):
        return self.kind == "claude"

    def __repr__(self):
        return f"Model({self.name!r}, {self.kind}, {self.ident!r})"

    def __eq__(self, other):
        return isinstance(other, Model) and (self.kind, self.ident, self.name) == \
            (other.kind, other.ident, other.name)

    def __hash__(self):
        return hash((self.kind, self.ident, self.name))


CLAUDE = [
    Model("default", "Claude Code's default", "claude", None, "no --model: what claude picks"),
    Model("fable", "Fable", "claude", "fable", "the latest Fable"),
    Model("opus", "Opus", "claude", "opus", "the latest Opus"),
    Model("sonnet", "Sonnet", "claude", "sonnet", "the latest Sonnet"),
    Model("haiku", "Haiku", "claude", "haiku", "the latest Haiku: fast, cheap"),
]
CLAUDE_ID = re.compile(r"claude-[a-z0-9][a-z0-9.\-]*(\[1m\])?$")
SERVER_PREFIX = "server:"


def claude_cli():
    """The `claude` executable, or None when Claude Code is not installed:
    $HYPR_CLAUDE_CLI when set ("none": not installed), else $PATH, else
    ~/.local/bin/claude (a session systemd started need not have
    ~/.local/bin on its PATH)."""
    forced = os.environ.get("HYPR_CLAUDE_CLI")
    if forced is not None:
        forced = forced.strip()
        return forced if forced and forced != "none" and os.access(forced, os.X_OK) else None
    found = shutil.which("claude")
    if found:
        return found
    local = os.path.join(os.path.expanduser("~"), ".local", "bin", "claude")
    return local if os.access(local, os.X_OK) else None


def claude_available():
    return claude_cli() is not None


def server_model(ident):
    """A model of the extra server ("server_url"), by the id its /models gives."""
    ident = str(ident)
    return Model(SERVER_PREFIX + ident, ident, "server", ident, "the OpenAI-compatible server")


# -- LM Studio's models, cached ----------------------------------------------
def _stamp():
    """The model folders and their mtimes: a download or a delete changes it."""
    out = []
    try:
        for pub in sorted(os.scandir(LMS_MODELS), key=lambda e: e.name):
            if not pub.is_dir():
                continue
            out.append([pub.name, pub.stat().st_mtime])
            for model in sorted(os.scandir(pub.path), key=lambda e: e.name):
                out.append([pub.name + "/" + model.name, model.stat().st_mtime])
    except OSError:
        pass
    return out


def _read_cache():
    try:
        with open(CACHE) as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def stale():
    """True when the cache does not describe the model folders as they are."""
    return os.access(LMS, os.X_OK) and _read_cache().get("stamp") != _stamp()


def _daemon_running():
    """Is LM Studio's daemon (llmster, or the app) up? From /proc: asking
    lms would wake it."""
    for pid in os.listdir("/proc"):
        if pid.isdigit():
            try:
                with open(f"/proc/{pid}/comm") as handle:
                    if handle.read().strip() in ("llmster", "lm-studio", "LM Studio"):
                        return True
            except OSError:
                pass
    return False


def refresh(timeout=40):
    """`lms ls --json` again, into the cache. Blocking (seconds): a thread.
    lms wakes the daemon to answer; one that was not up before is put back
    down after (hundreds of MB otherwise left behind by a model list)."""
    stamp = _stamp()
    was_up = _daemon_running()
    try:
        out = subprocess.run([LMS, "ls", "--json"], capture_output=True, text=True,
                             timeout=timeout).stdout
        rows = json.loads(out[out.index("["):])
    except (OSError, subprocess.SubprocessError, ValueError):
        return False
    finally:
        if not was_up and _daemon_running():
            try:
                subprocess.run([LMS, "daemon", "down"], capture_output=True, timeout=20)
            except (OSError, subprocess.SubprocessError):
                pass
    keep = [{k: r.get(k) for k in ("modelKey", "displayName", "paramsString", "sizeBytes",
                                   "maxContextLength", "trainedForToolUse", "vision", "path")}
            | {"quant": (r.get("quantization") or {}).get("name")}
            for r in rows if isinstance(r, dict) and r.get("type") == "llm" and r.get("modelKey")]
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    tmp = CACHE + ".tmp"
    with open(tmp, "w") as handle:
        json.dump({"stamp": stamp, "time": time.time(), "models": keep}, handle)
    os.replace(tmp, CACHE)
    return True


def _aliases(keys):
    """key -> short alias: the publisher off, three dash parts, more on a clash."""
    parts = {k: re.sub(r"-gguf$", "", k.split("/")[-1].lower()).split("-") for k in keys}
    out = {}
    for key in keys:
        n = 3
        while True:
            alias = "-".join(parts[key][:n])
            clash = [o for o in keys if o != key and "-".join(parts[o][:n]) == alias]
            if not clash or n >= len(parts[key]):
                break
            n += 1
        out[key] = alias
    return out


def local_models():
    """[Model] from the cache, as it is (refresh() is the caller's to start)."""
    rows = _read_cache().get("models") or []
    aliases = _aliases([r["modelKey"] for r in rows])
    out = []
    for r in rows:
        gb = (r.get("sizeBytes") or 0) / 1e9
        bits = [b for b in (r.get("paramsString"), r.get("quant"), f"{gb:.1f} GB" if gb else "") if b]
        out.append(Model(aliases[r["modelKey"]], r.get("displayName") or r["modelKey"], "local",
                         r["modelKey"], " · ".join(bits), r.get("path") or "", r.get("vision")))
    out.sort(key=lambda m: m.name)
    return out


def all_models():
    """Claude's (only with the claude CLI installed), then LM Studio's."""
    return (CLAUDE if claude_available() else []) + local_models()


# -- names -> models -----------------------------------------------------------
def resolve(word, models=None, prefix=True):
    """The Model `word` names, or None. Exact alias or key first (any case),
    then a full Claude id, then -- local models only -- an unambiguous start
    of an alias, MIN_PREFIX letters or more."""
    if not word:
        return None
    w = word.strip().lower()
    if w.startswith(SERVER_PREFIX) and len(w) > len(SERVER_PREFIX):
        return server_model(word.strip()[len(SERVER_PREFIX):])
    models = all_models() if models is None else models
    for m in models:
        if w == m.name or (m.ident and w == m.ident.lower()) or \
                (m.local and w == m.ident.lower().split("/")[-1]):
            return m
    if CLAUDE_ID.match(w) and claude_available():
        return Model(w, w, "claude", w, "a full model id")
    if prefix and len(w) >= MIN_PREFIX:
        hits = [m for m in models if m.local and
                (m.name.startswith(w) or m.ident.lower().split("/")[-1].startswith(w))]
        if len(hits) == 1:
            return hits[0]
    return None


def split_model(text, models=None):
    """("opus", "why is my build slow") -> (Model, rest) when the first word
    names a model; (None, text) otherwise. "default" is not taken from a
    prompt ("?default gateway on linux" is a question)."""
    stripped = text.lstrip()
    first, _, rest = stripped.partition(" ")
    if not first or first.lower() == "default":
        return None, text
    model = resolve(first, models)
    return (model, rest.lstrip()) if model else (None, text)


# -- settings -------------------------------------------------------------------
def settings():
    try:
        with open(SETTINGS) as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        data = {}
    data = data if isinstance(data, dict) else {}
    return {**DEFAULTS, **{k: v for k, v in data.items() if isinstance(v, str) and v}}


def _raw_settings():
    try:
        with open(SETTINGS) as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def local_options():
    """(context, parallel) for ensure_local: llm.json's "context" and
    "parallel", LOCAL_CONTEXT and None (LM Studio's default) when unset or
    out of range."""
    data = _raw_settings()
    ctx, par = data.get("context"), data.get("parallel")
    ok_ctx = isinstance(ctx, int) and CONTEXT_RANGE[0] <= ctx <= CONTEXT_RANGE[1]
    ok_par = isinstance(par, int) and PARALLEL_RANGE[0] <= par <= PARALLEL_RANGE[1]
    return (ctx if ok_ctx else LOCAL_CONTEXT), (par if ok_par else None)


def set_option(key, value):
    """`llm_models.py set KEY VALUE`, checked: ValueError says why not."""
    if key in ROLES:
        model = resolve(value, prefix=False)
        if model is None:
            raise ValueError(f"no model {value!r}")
        save_setting(key, model.name)
        return
    if key == "context":
        n = int(value)
        if not CONTEXT_RANGE[0] <= n <= CONTEXT_RANGE[1]:
            raise ValueError(f"context is {CONTEXT_RANGE[0]} to {CONTEXT_RANGE[1]} tokens")
        save_setting(key, n)
        return
    if key == "server_url":
        value = str(value or "").strip().rstrip("/")
        if value in ("", "none", "off"):
            save_setting(key, None)
            return
        if not re.match(r"https?://[^\s/]+", value):
            raise ValueError("server_url is an http:// or https:// URL, like http://localhost:11434/v1")
        save_setting(key, value)
        return
    if key == "server_key":
        value = str(value or "").strip()
        save_setting(key, None if value in ("", "none") else value)
        return
    if key == "parallel":
        if value == "auto":
            save_setting(key, None)
            return
        n = int(value)
        if not PARALLEL_RANGE[0] <= n <= PARALLEL_RANGE[1]:
            raise ValueError(f"parallel is {PARALLEL_RANGE[0]} to {PARALLEL_RANGE[1]} slots, or auto")
        save_setting(key, n)
        return
    limits = _limits_module()
    if key in limits.KEYS:
        limits.set_limit(key, value)
        return
    raise ValueError(f"no setting {key!r}")


def save_setting(key, name):
    """One key of llm.json written (None removes it); the others, of any
    type, kept as they are."""
    data = _raw_settings()
    if name is None:
        data.pop(key, None)
    else:
        data[key] = name
    os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
    tmp = SETTINGS + ".tmp"
    with open(tmp, "w") as handle:
        json.dump(data, handle, indent=2)
    if data.get("server_key"):
        os.chmod(tmp, 0o600)        # an API key in it: yours only
    os.replace(tmp, SETTINGS)


def chosen(key="default", models=None):
    """The Model the setting names -- its fallback when it names none now (a
    local model deleted since), and the first local model when that is a
    Claude one and Claude Code is not installed. None: no model at all."""
    return chosen_note(key, models)[0]


def chosen_note(key="default", models=None):
    """(Model or None, note): chosen(), and why it is not what the setting
    says ("" when it is)."""
    models = all_models() if models is None else models
    name = settings()[key]
    model = resolve(name, models, prefix=False)
    if model is not None:
        return model, ""
    model = resolve(DEFAULTS[key], models)
    if model is not None:
        return model, (f"{name} is not installed any more: {model.name} instead" if name != DEFAULTS[key] else "")
    first = next((m for m in models if m.local), None)
    if first is None:
        return None, f"no model to use for {key}: no local model in LM Studio" + (
            "" if claude_available() else ", and Claude Code is not installed")
    claude_named = name in [m.name for m in CLAUDE] or bool(CLAUDE_ID.match(name.lower()))
    why = (f"{name} is a Claude model and Claude Code is not installed: {first.name} (local) instead"
           if claude_named and not claude_available() else f"{name} is not installed: {first.name} instead")
    return first, why


def _gpu_module():
    """scripts/llm-gpu.py (the fit calculator), imported on first use only."""
    import importlib.util
    mod = sys.modules.get("llm_gpu")
    if mod is None:
        spec = importlib.util.spec_from_file_location(
            "llm_gpu", os.path.join(os.path.dirname(os.path.abspath(__file__)), "llm-gpu.py"))
        mod = importlib.util.module_from_spec(spec)
        sys.modules["llm_gpu"] = mod
        spec.loader.exec_module(mod)
    return mod


def _limits_module():
    """scripts/llm-limits.py (lmstudio.service's limits), imported on first
    use only."""
    import importlib.util
    mod = sys.modules.get("llm_limits")
    if mod is None:
        spec = importlib.util.spec_from_file_location(
            "llm_limits", os.path.join(os.path.dirname(os.path.abspath(__file__)), "llm-limits.py"))
        mod = importlib.util.module_from_spec(spec)
        sys.modules["llm_limits"] = mod
        spec.loader.exec_module(mod)
    return mod


def _gamemode_on():
    """lua/gamemode.lua's own test: animations off is gamemode on."""
    try:
        out = subprocess.run(["hyprctl", "getoption", "animations:enabled", "-j"], capture_output=True,
                             text=True, timeout=3).stdout
        answer = json.loads(out)
        return answer.get("bool") is False or answer.get("int") == 0
    except (OSError, subprocess.SubprocessError, ValueError, AttributeError):
        return False


def quick_choice(model=None):
    """(Model, why) for a ?? with no model typed: `model` (default: the
    "quick" setting) as it is when it is a Claude one, or a local one that
    fits next to what is on the card now; else haiku, `why` saying so.
    Blocking (nvidia-smi and /proc, ~50 ms): call it in a thread. The
    reasoning: the module docstring."""
    model = model or chosen("quick")
    if model is None or not model.local:
        return model, ""
    haiku = resolve("haiku")
    if haiku is None:
        return model, ""            # no Claude to give way to: the local one as it is
    if _gamemode_on():
        return haiku, f"gamemode is on: haiku instead of {model.name}"
    try:
        verdict = _gpu_module().fit_now(model)
    except Exception:       # a broken calculator must not cost the answer
        verdict = None
    if verdict and verdict["verdict"] == "won't fit":
        return haiku, f"{model.name} would not fit next to what is loaded: haiku instead"
    return model, ""


# -- LM Studio's server, and Claude Code's --model ---------------------------------
def server_port():
    """LM Studio's port, from its own config (no node start for this)."""
    try:
        with open(os.path.join(HOME, ".lmstudio", ".internal", "http-server-config.json")) as h:
            return int(json.load(h).get("port") or 1234)
    except (OSError, ValueError, TypeError):
        return 1234


def launch_spec(model):
    """The extra `claude` argv for a Claude model (["--model", ID], or []
    for Claude Code's own default). Only Claude models run through the
    claude CLI: a local or server model is the chat engine's."""
    if model is None or model.ident is None or not model.claude:
        return []
    return ["--model", model.ident]


def _lms(*args, timeout=30):
    return subprocess.run([LMS, *args], capture_output=True, text=True, timeout=timeout)


def _json_out(text):
    start = min([i for i in (text.find("["), text.find("{")) if i >= 0] or [-1])
    return json.loads(text[start:]) if start >= 0 else None


def ensure_local(model, status=lambda text: None):
    """LM Studio's server up and `model` loaded: (True, "") or (False, why).
    Blocking for as long as a load takes (a 27B: tens of seconds)."""
    import urllib.error
    import urllib.request
    name = model.name
    context, parallel = local_options()
    if not os.access(LMS, os.X_OK):
        return False, f"LM Studio's lms CLI is not at {LMS}"
    try:
        limits = _limits_module()
    except Exception:       # a broken limits script must not cost the model: the old way
        limits = None
    try:
        status(f"starting LM Studio for {name}…")
        if limits is not None:
            limits.ensure_daemon(status)    # a line of its own when it runs outside the limits
        state = _json_out(_lms("server", "status", "--json").stdout) or {}
        if not state.get("running"):
            started = _lms("server", "start", timeout=60)
            if started.returncode:
                return False, "lms server start failed: " + (started.stderr or started.stdout).strip()[-300:]
        port = server_port()
        # The OpenAI API's model list: what every caller here speaks.
        try:
            body = urllib.request.urlopen(f"http://localhost:{port}/v1/models", timeout=10).read()
        except urllib.error.HTTPError as exc:
            body = exc.read()
        except OSError as exc:
            return False, f"LM Studio's server on port {port} does not answer: {exc}"
        try:
            ok = isinstance(json.loads(body).get("data"), list)
        except (ValueError, AttributeError):
            ok = False
        if not ok:
            return False, f"LM Studio on port {port} does not answer GET /v1/models (the OpenAI API)"
        loaded = _json_out(_lms("ps", "--json").stdout) or []
        mine = [m for m in loaded if isinstance(m, dict) and m.get("modelKey") == model.ident]
        if any((m.get("contextLength") or 0) >= context for m in mine):
            return True, ""
        for m in mine:      # loaded by hand or JIT, with a context smaller than llm.json's
            status(f"reloading {name} with a {context // 1024}k context…")
            _lms("unload", m.get("identifier") or model.ident)
        _make_room(model, [m for m in loaded if isinstance(m, dict)], status)
        status(f"loading {name}…")
        ooms = limits.oom_kills() if limits is not None else None
        slots = ["--parallel", str(parallel)] if parallel else []
        proc = subprocess.Popen([LMS, "load", model.ident, "-y", "-c", str(context),
                                 "--ttl", str(LOCAL_TTL)] + slots,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        buf, last = b"", None
        while True:
            chunk = proc.stdout.read1(4096) if hasattr(proc.stdout, "read1") else proc.stdout.read(64)
            if not chunk:
                break
            buf = (buf + chunk)[-4096:]
            pct = re.findall(rb"(\d+)%", chunk)
            if pct and pct[-1] != last:
                last = pct[-1]
                status(f"loading {name}… {int(last)} %")
        code = proc.wait(timeout=30)
        if code:
            if limits is not None:
                why = limits.oom_reason(ooms, limits.oom_kills(), name, limits.limits()["ram_limit_gb"])
                if why:
                    return False, why
            tail = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", buf.decode(errors="replace"))
            tail = tail.replace("\r", "\n").strip().splitlines()
            return False, f"lms load {model.ident} failed: " + (tail[-1] if tail else f"exit {code}")
        return True, ""
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"LM Studio: {exc}"


def _make_room(model, loaded, status):
    """Before `model` is loaded: when it would not fit on the card next to
    what is there, the loaded models that are idle and smaller than it are
    unloaded first -- a quick-answer model left loaded gives way to the
    chat window's big one (it comes back in seconds; the big one would
    otherwise load partly into RAM, and be slow for the whole session).
    A busy model, or a bigger one, is never touched."""
    try:
        verdict = _gpu_module().fit_now(model)
    except Exception:       # the calculator is advice: never a reason not to load
        return
    if not verdict or verdict["verdict"] != "won't fit":
        return
    size = next((r.get("sizeBytes") or 0 for r in _read_cache().get("models") or []
                 if r.get("modelKey") == model.ident), 0)
    for m in loaded:
        if m.get("type", "llm") == "llm" and m.get("status") == "idle" and not m.get("queued") \
                and (m.get("sizeBytes") or 0) < size and m.get("modelKey") != model.ident:
            status(f"unloading the idle {m['modelKey'].split('/')[-1]} to make room…")
            try:
                _lms("unload", m.get("identifier") or m["modelKey"])
            except (OSError, subprocess.SubprocessError):
                pass


def free_local():
    """Every model unloaded and the server stopped (the GPU's memory back)."""
    for args in (("unload", "--all"), ("server", "stop")):
        try:
            _lms(*args)
        except (OSError, subprocess.SubprocessError):
            pass


# -- downloads: the launcher's ?get ---------------------------------------------
# `llm_models.py get REPO [VARIANT]` is what the launcher starts (in a scope
# of its own, so a launcher restart does not end it): `lms get
# https://huggingface.co/REPO@VARIANT -y --gguf` -- the URL form, since a bare
# "author/repo" is looked up on LM Studio's hub, not Hugging Face; "@q4_k_m"
# picks that file (lms fails at once, downloading nothing, on a variant the
# repo has not got; without one, -y takes lms's own pick for this hardware,
# Q8_0 for a small model). Its progress bar is read off the pipe and shown as
# one notification replaced in place, at most once a second; then the final
# one, and the cache refreshed so the model is in ?models and the chat window's
# picker. A lock file per repo under DL_DIR, held (flock) for as long as the
# download runs, keeps a second one of the same repo from starting.
DL_DIR = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "llm-downloads")
HF = "https://huggingface.co"
DL_ICON = "folder-download"
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b[78]")
_PROGRESS = re.compile(r"([\d.]+)%\s*\|\s*([\d.]+ ?[KMGT]?B) / ([\d.]+ ?[KMGT]?B)\s*\|\s*"
                       r"([\d.]+ ?[KMGT]?B/s)\s*\|\s*ETA ([\d:]+)")


def _lock_path(repo):
    return os.path.join(DL_DIR, re.sub(r"[^a-z0-9._-]", "_", repo.lower()) + ".lock")


def downloading(repo):
    """True while a `get` of `repo` holds its lock."""
    import fcntl
    try:
        with open(_lock_path(repo)) as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except FileNotFoundError:
        return False
    except OSError:
        return True             # held: EWOULDBLOCK
    return False


def _take_lock(repo):
    """The open lock file (keep it open), or None when another holds it."""
    import fcntl
    os.makedirs(DL_DIR, exist_ok=True)
    handle = open(_lock_path(repo), "a")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def installed_repos():
    """{"author/repo" lowercased}: the folders lms get downloads into."""
    return {entry[0].lower() for entry in _stamp() if "/" in entry[0]}


def model_for_repo(repo, models=None):
    """The local Model downloaded from Hugging Face's `repo`, or None: by
    lms ls's path ("author/repo/file.gguf"), else -- LM Studio's indexed
    keys ("qwen/qwen3.6-27b" for lmstudio-community/Qwen3.6-27B-GGUF) --
    the longest key whose last part starts the repo's name."""
    models = [m for m in (local_models() if models is None else models) if m.local]
    low = repo.lower()
    for m in models:
        if m.path.lower().startswith(low + "/"):
            return m
    base = re.sub(r"-gguf$", "", low.split("/")[-1])
    hits = [m for m in models if "/" in m.path and m.path.count("/") == 1
            and base.startswith(m.ident.lower().split("/")[-1])]
    return max(hits, key=lambda m: len(m.ident), default=None)


def _notify(summary, body, replace=None, value=None, sticky=False, icon=DL_ICON):
    """notify-send, `replace` the id of the one to update; the id back."""
    argv = ["notify-send", "-a", "LM Studio", "-i", icon, "-p"]
    if replace:
        argv += ["-r", str(replace)]
    if value is not None:
        argv += ["-h", f"int:value:{int(value)}"]
    if sticky:
        argv += ["-t", "0", "-u", "low"]
    try:
        out = subprocess.run(argv + [summary, body], capture_output=True, text=True,
                             timeout=5).stdout.strip()
        return int(out.splitlines()[-1]) if out else replace
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return replace


def _clean(raw):
    text = _ANSI.sub("", raw.decode(errors="replace")).replace("\r", "\n")
    return [line.strip(" ⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏") for line in text.splitlines() if line.strip()]


def get(repo, variant=""):
    """The download, start to end (blocking: the launcher runs it as a
    process of its own). 0 on success."""
    name = repo + (f" {variant}" if variant else "")
    lock = _take_lock(repo)
    if lock is None:
        _notify("Already downloading", f"{repo} is being downloaded already", icon="dialog-information")
        return 1
    spec = f"{HF}/{repo}" + (f"@{variant.lower()}" if variant else "")
    nid = _notify("Downloading " + name, "asking LM Studio…", value=0, sticky=True)
    refresh()
    before = {m.ident for m in local_models()}
    tail, last, already = [], 0.0, False
    try:
        proc = subprocess.Popen([LMS, "get", spec, "-y", "--gguf"], stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        buf = b""
        while True:
            chunk = proc.stdout.read1(65536)
            if not chunk:
                break
            buf = (buf + chunk)[-8192:]
            lines = _clean(buf)
            tail = lines[-6:]
            already = already or any("already downloaded" in line for line in lines)
            hit = None
            for line in reversed(lines):
                hit = _PROGRESS.search(line)
                if hit:
                    break
            if hit and time.monotonic() - last >= 1:
                last = time.monotonic()
                pct, done, total, speed, eta = hit.groups()
                nid = _notify("Downloading " + name, f"{float(pct):.0f} %  ·  {done} of {total}"
                              f"  ·  {speed}  ·  {eta} left", nid, float(pct), sticky=True)
        code = proc.wait()
    except (OSError, subprocess.SubprocessError) as exc:
        code, tail = 1, [str(exc)]
    if code:
        why = next((t for t in reversed(tail) if t.lower().startswith("error")), tail[-1] if tail else
                   f"lms exited with {code}")
        _notify("Download failed: " + repo, why[:300], nid, icon="dialog-error")
        return 1
    refresh()
    after = local_models()
    new = [m for m in after if m.ident not in before]
    model = new[0] if new else model_for_repo(repo, after)
    use = f" -- type ?{model.name} to use it" if model else ""
    _notify(("Already downloaded: " if already and not new else "Downloaded ") + name,
            (f"{model.label} · {model.detail}" if model else "in ~/.lmstudio/models") + use, nid,
            icon="emblem-default")
    lock.close()
    return 0


def select(repo):
    """`llm_models.py select REPO`, in the launcher's kitty: `lms get --select`
    (the variant picked by hand, its progress on the terminal), then the
    cache refreshed; the window waits for Enter."""
    lock = _take_lock(repo)
    if lock is None:
        print(f"{repo} is being downloaded already")
    else:
        code = subprocess.call([LMS, "get", f"{HF}/{repo}", "--select", "--gguf"])
        if code == 0:
            print("\nlooking for it in lms ls…", flush=True)
            refresh()
            model = model_for_repo(repo)
            if model:
                print(f"{model.label} ({model.detail}) -- type ?{model.name} in the launcher to use it")
        lock.close()
    try:
        input("press Enter ")
    except EOFError:
        pass


if __name__ == "__main__":
    if sys.argv[1:2] == ["get"] and len(sys.argv) > 2:
        sys.exit(get(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else ""))
    if sys.argv[1:2] == ["select"] and len(sys.argv) > 2:
        sys.exit(select(sys.argv[2]))
    if sys.argv[1:2] == ["set"] and len(sys.argv) == 4:
        try:
            set_option(sys.argv[2], sys.argv[3])
        except ValueError as exc:
            sys.exit(f"llm_models: {exc}")
        sys.exit(0)
    if sys.argv[1:2] == ["refresh"]:
        print("ok" if refresh() else "lms ls failed")
    for m in all_models():
        print(f"{m.kind:6} {m.name:24} {m.ident or '-':55} {m.detail}")
    print("claude:", claude_cli() or "not installed (Claude models are not offered)")
    print("settings:", {k: ("…" if k == "server_key" else v) for k, v in settings().items()})
