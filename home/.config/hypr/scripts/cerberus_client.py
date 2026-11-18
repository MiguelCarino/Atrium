#!/usr/bin/env python3
"""Cerberus, the self-hosted LLM runtime (github.com/MiguelCarino/Cerberus),
as the desktop's model manager (llm_manager.py) sees it: its models, and
load / unload / delete for them. Optional: without Cerberus, available()
is False and nothing else is asked.

    base()          http://HOST:PORT -- $CERBERUS_URL, else the service's
                    own server.listen (~/.config/cerberus/config.json),
                    else 127.0.0.1:7340
    models()        GET /v1/models: every model Cerberus serves -- llama.cpp,
                    LM Studio, Ollama, cloud providers -- with its engine
                    (owned_by), local, loaded, context, vision. Keyless:
                    /v1 from this machine needs no token (server.local_no_auth,
                    Cerberus' default), so the list never reads the token
    action(id, a)   POST /api/models/<id>/{load,unload,delete}: the control
                    API takes the service's bearer token, read from its
                    config.json when the action is asked for -- the way
                    Cerberus' docs/DESKTOP.md says a desktop client
                    authenticates -- and never kept or written anywhere
    chat_url()      the OpenAI base the chat points at (llm.json server_url)
                    to talk to Cerberus' models: base() + /v1

Every call blocks (HTTP, up to minutes for a load): run it in a thread.

    cerberus_client.py              the models, as text
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

DEFAULT = "http://127.0.0.1:7340"
CONFIG = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
                      "cerberus", "config.json")
ENGINES = {"llamacpp": "llama.cpp", "lmstudio": "LM Studio", "ollama": "Ollama"}
DELETABLE = ("llamacpp", "ollama")   # LM Studio's are deleted on the manager's On this PC page
LOAD_TIMEOUT = 600


class CerberusError(Exception):
    pass


def _server_conf():
    """config.json's "server" block ({} when unreadable)."""
    try:
        with open(CONFIG) as handle:
            server = json.load(handle).get("server")
        return server if isinstance(server, dict) else {}
    except (OSError, ValueError, AttributeError):
        return {}


def base():
    env = os.environ.get("CERBERUS_URL", "").strip().rstrip("/")
    if env:
        return env[:-3] if env.endswith("/v1") else env
    listen = str(_server_conf().get("listen") or "").strip()
    if listen:
        host, _, port = listen.rpartition(":")
        if host in ("", "0.0.0.0", "[::]", "::"):
            host = "127.0.0.1"
        if port.isdigit():
            return f"http://{host}:{port}"
    return DEFAULT


def chat_url():
    return base() + "/v1"


def installed():
    """Cerberus is set up here: its config, or $CERBERUS_URL."""
    return bool(os.environ.get("CERBERUS_URL")) or os.path.isfile(CONFIG)


def _request(method, path, token=None, timeout=5):
    req = urllib.request.Request(base() + path, method=method, data=b"{}" if method == "POST" else None,
                                 headers={"Content-Type": "application/json", "User-Agent": "Atrium llm_manager"})
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as exc:
        raise CerberusError(_error_text(exc)) from None
    except (OSError, ValueError) as exc:
        raise CerberusError(f"Cerberus at {base()} did not answer: {getattr(exc, 'reason', exc)}") from None


def _error_text(exc):
    try:
        body = json.loads(exc.read() or b"null")
    except (OSError, ValueError):
        body = None
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, dict):
        err = err.get("message")
    return str(err or f"Cerberus said {exc.code}")


def models():
    """[{"id", "engine", "engine_label", "local", "loaded", "ctx", "vision"}],
    local first then by id. CerberusError when it does not answer."""
    data = _request("GET", "/v1/models")
    rows = data.get("data") if isinstance(data, dict) else None
    out = []
    for m in rows if isinstance(rows, list) else []:
        if not isinstance(m, dict) or not m.get("id"):
            continue
        engine = str(m.get("owned_by") or "")
        extra = m.get("cerberus") if isinstance(m.get("cerberus"), dict) else {}
        out.append({"id": str(m["id"]), "engine": engine, "engine_label": ENGINES.get(engine, engine or "?"),
                    "local": bool(m.get("local")), "loaded": bool(m.get("loaded")),
                    "ctx": int(m.get("context_length") or extra.get("ctx") or 0),
                    "vision": bool(m.get("vision") or extra.get("vision"))})
    out.sort(key=lambda r: (not r["local"], r["engine"], r["id"].lower()))
    return out


def can_control():
    """The control API's token is there to be read (load / unload / delete)."""
    return bool(_server_conf().get("token"))


def action(model_id, what):
    """load | unload | delete one model. CerberusError with Cerberus' reason
    (no room, in use, not deletable, unknown model) when it refuses."""
    if what not in ("load", "unload", "delete"):
        raise ValueError(what)
    token = _server_conf().get("token")
    if not token:
        raise CerberusError(f"no Cerberus token in {CONFIG}: use its web UI ({base()})")
    path = "/api/models/" + urllib.parse.quote(model_id, safe="/") + "/" + what
    return _request("POST", path, token=token, timeout=LOAD_TIMEOUT if what == "load" else 60)


if __name__ == "__main__":
    print("Cerberus:", base(), "" if installed() else "(not set up here)")
    try:
        for m in models():
            print(f"{m['engine_label']:10} {m['id']:60} {'loaded' if m['loaded'] else '':7} "
                  f"{'local' if m['local'] else 'cloud':6} ctx {m['ctx']}{'  vision' if m['vision'] else ''}")
    except CerberusError as exc:
        sys.exit(str(exc))
