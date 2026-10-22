#!/usr/bin/env python3
"""The local worker: an MCP server (stdio) that lets a coding agent (any MCP
client; Claude Code, for one) hand bulk, low-stakes text jobs to the local
"worker" model (Settings > AI & models; llm_models.py's "worker" setting)
instead of spending its own tokens on them:
summarise a long log, tag or sort many files, pull fields out of documents,
draft a commit message or translation strings.

    claude mcp add --scope user local-worker -- python3 ~/.config/hypr/scripts/llm-worker.py
                                        (Claude Code; another client: its own way of
                                        adding a stdio MCP server)

One tool, `local_worker`:
    task    what to do, in plain words
    text    text to work on (optional)
    files   paths to work on (optional): read HERE, so their contents never
            pass through the agent's context -- that is the saving
    each    true: the task runs once per file, one answer per file (tagging,
            sorting); false (default): all of it in one prompt
It answers with the model's text, headed by which model wrote it: a small
model's draft, to be checked before it is relied on.

What it never does:
  - fall back to a cloud model: the job is local or it is refused, saying why
  - push anything off the GPU: when the worker would not fit next to what
    is loaded (llm-gpu.py's fit_now), or gamemode is on, it refuses
  - read what looks secret (~/.ssh, ~/.gnupg, keyrings, *.env, id_rsa*,
    names with secret/credential/password/token) -- refused per file
  - read a file in a folder you have not opened to it (folder_access.py,
    Settings > Privacy > Folder access): the first file of such a folder
    asks you on the desktop (who: "worker"; the `reason` argument is shown
    as the AI's reason), one prompt per folder per call; "Allow once" lasts
    for this call. No screen to ask on, no answer in time, or Deny: that
    folder's files are skipped and the tool's error says which folder needs
    access and how to grant it (Settings, or `folder-access.py allow DIR
    --who worker`)

Plain JSON-RPC over stdin/stdout, one message per line (MCP's stdio
transport); no mcp package needed. Logs go to stderr, which the client
keeps out of the protocol.
"""

import importlib.util
import json
import os
import re
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PROTOCOL = "2025-06-18"
TIMEOUT = 600               # one answer; a cold load of the model counts too
MAX_CHARS = 120_000         # per prompt: ~30k tokens, half of the 64k context
MAX_FILE = 2_000_000        # bytes; bigger files are refused, not read
MAX_FILES = 200

SECRET_DIRS = (".ssh", ".gnupg", ".password-store", ".local/share/keyrings", ".local/share/kwalletd")
SECRET_NAME = re.compile(r"secret|credential|password|passwd|token|^id_(rsa|dsa|ecdsa|ed25519)|"
                         r"\.env$|^\.env|\.pem$|\.key$", re.I)

SYSTEM = ("You are a careful assistant doing one bulk text job for a developer. Do exactly the task, "
          "answer only with the result (no preamble), and say plainly when the input does not contain "
          "what is asked for instead of guessing.")

TOOL = {
    "name": "local_worker",
    "description": (
        "Run a bulk, low-stakes text job on the local GPU model (free, private, nothing leaves the "
        "machine): summarise logs, tag/sort/classify many files, extract fields, draft commit "
        "messages or translation strings. Pass `files` as paths: they are read by the worker, so "
        "their contents do not enter your context. Use `each` to run the task once per file. The "
        "model is small: treat the answer as a draft to check, never for reasoning, code edits or "
        "anything where a wrong answer is costly. Refuses (with the reason) when the GPU is busy "
        "or gamemode is on; then do the job yourself."),
    "inputSchema": {
        "type": "object",
        "properties": {
            "task": {"type": "string", "description": "What to do, in plain words."},
            "text": {"type": "string", "description": "Text to work on (optional)."},
            "files": {"type": "array", "items": {"type": "string"},
                      "description": "Absolute paths to read and work on (optional)."},
            "each": {"type": "boolean",
                     "description": "Run the task once per file and answer per file (default false)."},
            "reason": {"type": "string",
                       "description": "Why these files are needed, in a few words: shown to the user when a "
                                      "folder needs their permission first."},
        },
        "required": ["task"],
    },
}


def _module(name, filename):
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return mod


def models():
    return _module("llm_models", "llm_models.py")


def access():
    return _module("folder_access", "folder_access.py")


def log(text):
    print(f"llm-worker: {text}", file=sys.stderr, flush=True)


# -- the job ---------------------------------------------------------------
def looks_secret(path):
    home = os.path.expanduser("~")
    real = os.path.realpath(path)
    if any(real == os.path.join(home, d) or real.startswith(os.path.join(home, d) + os.sep)
           for d in SECRET_DIRS):
        return True
    return bool(SECRET_NAME.search(os.path.basename(real)))


def read_file(path):
    """(text, None) or (None, why not)."""
    path = os.path.expanduser(path)
    if looks_secret(path):
        return None, "looks secret: not read"
    try:
        if os.path.getsize(path) > MAX_FILE:
            return None, f"bigger than {MAX_FILE // 1_000_000} MB: not read"
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError as exc:
        return None, exc.strerror or str(exc)
    if b"\0" in raw[:4096]:
        return None, "binary: not read"
    return raw.decode("utf-8", errors="replace"), None


def clip(text, limit):
    if len(text) <= limit:
        return text
    half = limit // 2
    return text[:half] + f"\n\n[... {len(text) - limit} characters cut ...]\n\n" + text[-half:]


def ready(role="worker"):
    """(Model, None) when the worker model can run now, else (None, why).
    `role`: another llm.json setting to check the same way ("quick":
    automations.py's plain-words rules); notify-digest.py uses this as is."""
    lm = models()
    model = lm.chosen(role)
    if model is None or model.name == "default":
        model = lm.chosen("default")
    if model is None or not model.local:
        return None, (f"the {role} setting names no local model (Settings > AI & models): "
                      "do the job yourself")
    if lm._gamemode_on():
        return None, "gamemode is on and the GPU belongs to the game: do the job yourself"
    try:
        verdict = lm._gpu_module().fit_now(model)
    except Exception:       # the calculator is advice
        verdict = None      # also None when the model is loaded already
    if verdict and verdict["verdict"] == "won't fit":
        return None, (f"{model.name} would not fit on the GPU next to what is loaded now: "
                      "do the job yourself")
    ok, why = lm.ensure_local(model, log)
    if not ok:
        return None, why
    return model, None


def ask(model, prompt, system=SYSTEM, extra=None):
    """The model's answer to one prompt. `extra`: more request fields
    (automations.py passes a response_format JSON schema)."""
    port = models().server_port()
    body = json.dumps({"model": model.ident, "temperature": 0.2, "stream": False,
                       "messages": [{"role": "system", "content": system},
                                    {"role": "user", "content": prompt}], **(extra or {})}).encode()
    req = urllib.request.Request(f"http://localhost:{port}/v1/chat/completions", data=body,
                                 headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        answer = json.load(resp)
    text = answer["choices"][0]["message"].get("content") or ""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def prompt_for(task, parts):
    """parts: [(label, text)] -> one prompt within MAX_CHARS."""
    share = MAX_CHARS // max(1, len(parts))
    body = "\n\n".join(f"=== {label} ===\n{clip(text, share)}" for label, text in parts)
    return f"Task: {task}\n\n{body}" if body else f"Task: {task}"


def run(args):
    """(text, is_error) for one tools/call."""
    task = (args.get("task") or "").strip()
    if not task:
        return "no task given", True
    files = args.get("files") or []
    if not isinstance(files, list) or len(files) > MAX_FILES:
        return f"files must be a list of at most {MAX_FILES} paths", True
    parts, skipped, blocked = [], [], []
    if args.get("text"):
        parts.append(("text", str(args["text"])))
    fa = access()
    session = fa.Session("worker")      # "Allow once" / Deny: for this call
    reason = str(args.get("reason") or task)[:300]
    for path in files:
        path = os.path.expanduser(str(path))
        if os.path.exists(path):
            ok, why = fa.request(path, "worker", reason, session=session)
            if not ok:
                skipped.append(f"{path}: {why}")
                blocked.append(why)
                continue
        text, why = read_file(path)
        if why:
            skipped.append(f"{path}: {why}")
        else:
            parts.append((path, text))
    if not parts:
        head = "nothing to work on" if not blocked else \
            "folder access needed: the user has not opened these files' folder(s) to the local worker"
        return head + ("".join("\n  " + s for s in skipped)), True

    model, why = ready()
    if model is None:
        return f"local worker refused: {why}", True

    try:
        if args.get("each"):
            out = [f"=== {label} ===\n{ask(model, prompt_for(task, [(label, text)]))}"
                   for label, text in parts]
            result = "\n\n".join(out)
        else:
            result = ask(model, prompt_for(task, parts))
    except (OSError, urllib.error.URLError, ValueError, KeyError, IndexError) as exc:
        return f"local worker failed ({model.name}): {exc}", True
    head = f"[local draft by {model.name}: check before relying on it]"
    tail = ("\n\nSkipped:\n  " + "\n  ".join(skipped)) if skipped else ""
    return f"{head}\n{result}{tail}", False


# -- MCP over stdio ---------------------------------------------------------
def handle(msg):
    """The response for one JSON-RPC message, or None (a notification)."""
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:
        return None
    if method == "initialize":
        version = (msg.get("params") or {}).get("protocolVersion") or PROTOCOL
        result = {"protocolVersion": version, "capabilities": {"tools": {}},
                  "serverInfo": {"name": "local-worker", "version": "1"}}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": [TOOL]}
    elif method == "tools/call":
        params = msg.get("params") or {}
        if params.get("name") != TOOL["name"]:
            return {"jsonrpc": "2.0", "id": mid,
                    "error": {"code": -32602, "message": f"no tool {params.get('name')!r}"}}
        text, err = run(params.get("arguments") or {})
        result = {"content": [{"type": "text", "text": text}], "isError": err}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"no method {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def main():
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        reply = handle(msg) if isinstance(msg, dict) else None
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
