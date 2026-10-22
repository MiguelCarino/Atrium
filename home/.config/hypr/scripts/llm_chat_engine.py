#!/usr/bin/env python3
"""The LLM chat window's own engine (llm-chat.py): a conversation with any
OpenAI-compatible chat-completions server, streamed as it is written, with a
handful of tools the model may call -- nothing in between, no CLI, no cloud
account needed. Claude Code is one more backend of the window, used only for
a Claude model and only when the `claude` CLI is installed; everything here
works without it.

No GTK here: the window runs a Run in a thread and is handed its events;
the launcher's ?? quick answers use stream() directly; the tests drive both
against a fake server.

WHERE IT ASKS (endpoint()):

    local    LM Studio's own server, http://localhost:<port>/v1 (the port
             from LM Studio's config, llm_models.server_port(): 1234 unless
             it says otherwise). The window readies the model first --
             llm_models.ensure_local: lmstudio.service started inside its
             limits, the server up, the model loaded with llm.json's
             context and an idle TTL -- and unloads it on request.
    server   one more OpenAI-compatible server, for Ollama
             (http://localhost:11434/v1), llama.cpp's llama-server
             (http://localhost:8080/v1), vLLM, or a remote provider: its
             base URL in llm.json "server_url" (Settings > AI & models, or
             `llm_models.py set server_url URL`), an API key, if it wants
             one, in "server_key" (or $LLM_SERVER_KEY, which wins). The key
             goes as "Authorization: Bearer KEY" to that server only. Its
             models are its GET /models (server_models(), asked in a thread).

ONE MESSAGE (Run, in a thread of its own -- never the GTK loop): POST
{base}/chat/completions with "stream": true, the conversation so far and,
unless the model turned them down, the tools. The answer comes as
server-sent events ("data: {json}" lines, "data: [DONE]" at the end), read
off the socket as they arrive: choices[0].delta.content (the reply,
rendered live), delta.reasoning_content or delta.reasoning (a thinking
model's reasoning: shown folded), delta.tool_calls (pieces of a call,
joined by index), and usage (stream_options.include_usage: the context the
status line counts). A model that writes its reasoning inline between
<think> and </think> has it taken out of the reply the same way
(ThinkSplitter). When the reply calls tools, each runs (below), its result
goes back as a "tool" message, and the model is asked again -- at most
MAX_STEPS times per message; the last time without tools, so it has to
answer with what it has.

A server or model without function calling (Ollama's "does not support
tools", llama-server without --jinja, an HTTP error to a request with
tools before anything was streamed): the same request again without tools,
and the window says "plain chat, no tools" for that model from then on.

Images go as image_url parts with data: URIs. llm_models knows from lms ls
which local models have vision; any other is tried, and a server that
turns the picture down gets a plain error saying the model may not see
images (the message is not kept, so the next one is not refused again).

THE TOOLS (TOOLS below, the model's names; each shown on its chip and card
as it is):

    read_file    a text file (line numbers, `offset` / `limit` lines, at
                 most READ_MAX bytes; binary refused)
    list_dir     a folder's entries, folders first
    search       file contents by regular expression and / or file names
                 by glob, under a folder (hidden folders, .git,
                 node_modules and the like skipped; SEARCH_HITS matches)
    run_command  `bash -c COMMAND` in the working directory, its own process
                 group (Esc ends it, and closing the window), stdin closed,
                 TIMEOUT_S seconds unless it asks for more (TIMEOUT_MAX),
                 stdout and stderr together, clipped
    write_file   a whole file, created or replaced (its folder made)
    edit_file    an exact string replaced in a file: old_string must be
                 there once (or replace_all), else nothing changes and the
                 model is told why

Every result is clipped to OUTPUT_MAX characters (head and tail kept).

READING goes through Folder access (folder_access.py, Settings > Privacy >
Folder access), as the assistant and the local worker do, under its own
name there ("chat": the LLM chat window): what read_file, list_dir and
search touch must be in a folder open to the chat. When one is not, the
desktop asks you (Deny / Allow once / Always allow); "Allow once" lasts for
the conversation (Ctrl+N or another session forgets it). Open without
asking: the folders you typed yourself in this conversation (a path,
~/notes/x.md), and the working directory when it is not your home folder
itself (a --cwd, or the launcher's ?@folder, is your choice). Paths that
look secret or are system folders are never read, granted or not -- and
never written either.

PERMISSIONS: what may run without a yes depends on the window's mode (its
Ctrl+P menu, the same four as for Claude Code; policy()):

    Ask me        reads go (Folder access still decides); every
                  write_file, edit_file and run_command asks on a card
    Auto          reads go; a run_command on the read-only list goes
                  (safe_command(): ls, cat, head, grep, git status / log /
                  diff, ... -- one plain command, no ; & | ` $( < > or
                  newline, every path it names readable by Folder access
                  without asking); every other command and every write asks
    Accept edits  reads go; write_file / edit_file inside the working
                  directory go, outside it ask; commands ask
    Plan          read-only: only the reading tools are offered, and a
                  write or a command the model asks for anyway is refused
                  (it is told so) -- nothing is asked, nothing changes

A card's answers are the window's: Allow once, Allow for this session (a
rule the window keeps until the conversation ends), Deny with an optional
note -- the note reaches the model as the tool's result ("The user denied
this in the chat window: <note>"). Run.answer() takes them; the run waits
for an answer (Esc: every open question is a no).

SESSIONS: each conversation is a JSON file under
$XDG_STATE_HOME/hypr/llm-chat/sessions/<id>.json (mode 600): {"id",
"title" (the first message), "cwd", "model", "created", "updated",
"messages"} -- the OpenAI-format messages, an image kept only as the
words "[image]" (a picture is not written to disk). Written after every
answer; save_session / load_session / list_sessions / delete_session.
"""

import base64
import datetime
import fnmatch
import http.client
import json
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from urllib.parse import urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    import llm_models           # the registry and LM Studio's port: no GTK
except Exception:               # noqa: BLE001  (a bare default then)
    llm_models = None
try:
    import folder_access        # who may read which folder
except Exception:               # noqa: BLE001
    folder_access = None

STATE = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "hypr")
SESSIONS = os.path.join(STATE, "llm-chat", "sessions")
WHO = "chat"                # folder_access.py's name for this window
MAX_STEPS = 12              # tool rounds per message
OUTPUT_MAX = 12_000         # characters of one tool result the model gets
READ_MAX = 256 * 1024       # bytes read_file reads
LIST_MAX = 400              # entries list_dir lists
SEARCH_HITS = 200           # lines search returns
SEARCH_FILES = 20_000       # files search looks at
SEARCH_FILE_MAX = 2_000_000     # bytes: a bigger file is not searched
TIMEOUT_S = 120             # run_command's default
TIMEOUT_MAX = 600
CONNECT_S = 15              # to connect; reading waits as long as the model thinks
READ_S = 900
SKIP_DIRS = {".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache",
             ".pytest_cache", ".tox", "dist", "build", ".cache", ".next", "target"}
DENY_MESSAGE = "The user denied this in the chat window."


# -- where to ask ----------------------------------------------------------------------------
def lmstudio_base():
    port = llm_models.server_port() if llm_models is not None else 1234
    return f"http://localhost:{port}/v1"


def endpoint(kind="local"):
    """{"kind", "base", "key", "label"} for a model's kind: LM Studio's
    server for "local", llm.json's server for "server" (None: not set)."""
    if kind == "server":
        conf = llm_models.settings() if llm_models is not None else {}
        base = (conf.get("server_url") or "").strip().rstrip("/")
        if not base:
            return None
        key = os.environ.get("LLM_SERVER_KEY") or conf.get("server_key") or ""
        return {"kind": "server", "base": base, "key": key, "label": urlsplit(base).netloc or base}
    return {"kind": "local", "base": lmstudio_base(), "key": "", "label": "LM Studio"}


class ServerError(Exception):
    def __init__(self, status, message):
        super().__init__(f"HTTP {status}: {message}" if status else message)
        self.status, self.message = status, message


class Cancelled(Exception):
    pass


def _connect(base, timeout):
    parts = urlsplit(base)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ServerError(None, f"not an http(s) URL: {base!r}")
    cls = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
    conn = cls(parts.hostname, parts.port, timeout=timeout)
    return conn, parts.path.rstrip("/")


def _headers(ep):
    head = {"content-type": "application/json", "accept": "text/event-stream, application/json"}
    if ep.get("key"):
        head["authorization"] = "Bearer " + ep["key"]
    return head


def _error_text(raw):
    try:
        data = json.loads(raw)
    except ValueError:
        return raw.decode("utf-8", "replace").strip()[:500] or "no details"
    err = data.get("error") if isinstance(data, dict) else None
    if isinstance(err, dict):
        return str(err.get("message") or err)[:500]
    return str(err or data)[:500]


def server_models(ep, timeout=8):
    """The ids a server's GET /models lists. Blocking: a thread."""
    conn, path = _connect(ep["base"], timeout)
    try:
        conn.request("GET", path + "/models", headers=_headers(ep))
        resp = conn.getresponse()
        raw = resp.read()
        if resp.status != 200:
            raise ServerError(resp.status, _error_text(raw))
        data = json.loads(raw)
    except (OSError, ValueError, http.client.HTTPException) as exc:
        raise ServerError(None, str(exc)) from None
    finally:
        conn.close()
    rows = data.get("data") if isinstance(data, dict) else data
    return sorted(str(r["id"]) for r in rows or [] if isinstance(r, dict) and r.get("id"))


def stream(ep, body, holder=None):
    """POST /chat/completions with "stream": true: each SSE chunk as a dict,
    as it arrives. `holder` (a dict) gets "sock" -- another thread shuts it
    down to cancel (the read then ends) -- and is checked for "cancel"."""
    holder = holder if holder is not None else {}
    conn, path = _connect(ep["base"], CONNECT_S)
    try:
        payload = json.dumps(dict(body, stream=True)).encode()
        try:
            conn.request("POST", path + "/chat/completions", body=payload, headers=_headers(ep))
            holder["sock"] = conn.sock
            if holder.get("cancel"):
                raise Cancelled()
            conn.sock.settimeout(READ_S)
            resp = conn.getresponse()
        except (OSError, http.client.HTTPException) as exc:
            if holder.get("cancel"):
                raise Cancelled() from None
            raise ServerError(None, f"could not reach {ep['base']}: {exc}") from None
        if resp.status != 200:
            raise ServerError(resp.status, _error_text(resp.read()))
        kind = resp.getheader("content-type") or ""
        if "event-stream" not in kind:
            # A server that answered whole anyway: one chunk shaped like a delta.
            data = json.loads(resp.read() or b"{}")
            for choice in data.get("choices") or []:
                msg = choice.get("message") or {}
                yield {"choices": [{"index": 0, "delta": msg, "finish_reason": choice.get("finish_reason")}],
                       "usage": data.get("usage")}
            return
        data_lines = []
        while True:
            if holder.get("cancel"):
                raise Cancelled()
            try:
                line = resp.readline()
            except (OSError, http.client.HTTPException) as exc:
                if holder.get("cancel"):
                    raise Cancelled() from None
                raise ServerError(None, f"the stream broke off: {exc}") from None
            if not line:
                if holder.get("cancel"):
                    raise Cancelled()
                break
            line = line.rstrip(b"\r\n")
            if line.startswith(b"data:"):
                data_lines.append(line[5:].lstrip())
                continue
            if line or not data_lines:
                continue            # comments (": ping"), event: names, blank keep-alives
            data, data_lines = b"\n".join(data_lines), []
            if data.strip() == b"[DONE]":
                break
            try:
                chunk = json.loads(data)
            except ValueError:
                continue
            if isinstance(chunk, dict) and chunk.get("error"):
                raise ServerError(None, _error_text(data))
            if isinstance(chunk, dict):
                yield chunk
        if data_lines and data_lines != [b"[DONE]"]:
            try:
                chunk = json.loads(b"\n".join(data_lines))
                if isinstance(chunk, dict):
                    yield chunk
            except ValueError:
                pass
    finally:
        holder.pop("sock", None)
        conn.close()


class ThinkSplitter:
    """Reasoning written inline -- "<think>…</think>" -- out of the reply.
    feed(text) -> (reply text, reasoning text), holding back a tag cut in
    two between chunks."""

    OPEN, CLOSE = "<think>", "</think>"

    def __init__(self):
        self.inside, self.pending = False, ""

    def feed(self, text):
        buf, reply, think = self.pending + text, [], []
        self.pending = ""
        while buf:
            tag = self.CLOSE if self.inside else self.OPEN
            at = buf.find(tag)
            if at >= 0:
                (think if self.inside else reply).append(buf[:at])
                buf = buf[at + len(tag):]
                self.inside = not self.inside
                continue
            keep = next((n for n in range(len(tag) - 1, 0, -1) if buf.endswith(tag[:n])), 0)
            (think if self.inside else reply).append(buf[:len(buf) - keep])
            self.pending = buf[len(buf) - keep:]
            break
        return "".join(reply), "".join(think)

    def flush(self):
        rest, self.pending = self.pending, ""
        return ("", rest) if self.inside else (rest, "")


# -- the tools --------------------------------------------------------------------------------
def _fn(name, description, props, required=()):
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": props, "required": list(required)}}}


TOOLS = [
    _fn("read_file", "Read a text file. Returns its lines numbered. Use offset/limit for long files.",
        {"path": {"type": "string", "description": "File path, absolute or relative to the working directory."},
         "offset": {"type": "integer", "description": "First line to return (1-based, optional)."},
         "limit": {"type": "integer", "description": "How many lines (optional)."}}, ["path"]),
    _fn("list_dir", "List a folder's entries (folders end with /).",
        {"path": {"type": "string", "description": "Folder path; the working directory when left out."}}),
    _fn("search", "Search files under a folder: lines matching a regular expression (pattern), "
        "and/or file names matching a glob (glob, like *.py).",
        {"pattern": {"type": "string", "description": "Regular expression to find in file contents (optional)."},
         "glob": {"type": "string", "description": "File name glob, e.g. *.md (optional)."},
         "path": {"type": "string", "description": "Folder to search; the working directory when left out."}}),
    _fn("run_command", "Run a bash command in the working directory and return its output "
        "(stdout and stderr). Non-interactive: no input can be typed.",
        {"command": {"type": "string", "description": "The command line."},
         "description": {"type": "string", "description": "What it does, in a few words (shown to the user)."},
         "timeout": {"type": "integer", "description": f"Seconds before it is stopped (default {TIMEOUT_S}, "
                                                        f"at most {TIMEOUT_MAX})."}}, ["command"]),
    _fn("write_file", "Create or replace a whole file with the given content.",
        {"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]),
    _fn("edit_file", "Replace an exact piece of text in a file. old_string must occur exactly once "
        "(include surrounding lines to make it unique) unless replace_all is true.",
        {"path": {"type": "string"}, "old_string": {"type": "string"}, "new_string": {"type": "string"},
         "replace_all": {"type": "boolean"}}, ["path", "old_string", "new_string"]),
]
TOOL_NAMES = tuple(t["function"]["name"] for t in TOOLS)
READ_TOOLS = ("read_file", "list_dir", "search")
CHANGE_TOOLS = ("run_command", "write_file", "edit_file")
EDIT_TOOLS = ("write_file", "edit_file")


def tool_specs(mode):
    """The tools offered in a Permissions mode: Plan only the reading ones."""
    return [t for t in TOOLS if mode != "plan" or t["function"]["name"] in READ_TOOLS]


def canon(name, args):
    """(name, input) as the window's permission cards and chips know a tool
    (Claude Code's shapes: Bash {command}, Write {file_path, content}, Edit
    {file_path, old_string, new_string}, Read, LS, Grep), so the card's
    summary, its diff, and the session rules are the same code for both
    backends."""
    a = args if isinstance(args, dict) else {}
    path = str(a.get("path") or "")
    if name == "run_command":
        out = {"command": str(a.get("command") or "")}
        if a.get("description"):
            out["description"] = str(a["description"])
        return "Bash", out
    if name == "write_file":
        return "Write", {"file_path": path, "content": str(a.get("content") or "")}
    if name == "edit_file":
        return "Edit", {"file_path": path, "old_string": str(a.get("old_string") or ""),
                        "new_string": str(a.get("new_string") or ""),
                        **({"replace_all": True} if a.get("replace_all") else {})}
    if name == "read_file":
        return "Read", {"file_path": path}
    if name == "list_dir":
        return "LS", {"path": path or "."}
    if name == "search":
        return "Grep", {k: str(a[k]) for k in ("pattern", "glob", "path") if a.get(k)}
    return name, dict(a)


def resolve(path, cwd):
    path = os.path.expanduser(str(path or "").strip().strip("\"'")) or "."
    return os.path.normpath(path if os.path.isabs(path) else os.path.join(cwd or "/", path))


def under(path, folder):
    folder = folder.rstrip(os.sep) or os.sep
    return path == folder or path.startswith(folder.rstrip(os.sep) + os.sep)


def clip(text, limit=OUTPUT_MAX):
    if len(text) <= limit:
        return text
    head = limit * 2 // 3
    tail = limit - head
    return text[:head] + f"\n[... {len(text) - limit} characters cut ...]\n" + text[-tail:]


def deny_message(note=""):
    note = (note or "").strip()
    return f"The user denied this in the chat window: {note}" if note else DENY_MESSAGE


# Auto mode's read-only commands: one of these, as one plain command. Left
# out on purpose: anything that can write through an option (sort -o, uniq
# IN OUT, tree -o, rg --pre runs a program, sed -i, tee).
SAFE_COMMANDS = {"ls", "pwd", "cat", "head", "tail", "wc", "grep", "egrep", "fgrep", "stat", "file",
                 "du", "df", "which", "whoami", "id", "uname", "date", "echo", "diff", "cmp", "cut",
                 "realpath", "readlink", "basename", "dirname", "nproc", "uptime", "free", "lsblk", "true",
                 "find", "git"}
SAFE_GIT = {"status", "log", "diff", "show", "rev-parse", "ls-files", "blame", "describe", "shortlog"}
UNSAFE_FIND = {"-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprint0", "-fprintf", "-fls"}
_SHELL_SIGNS = re.compile(r"[;&|`\n<>$*?\[\]{}]")


def safe_command(command, cwd, readable=lambda path: False):
    """Auto mode's judgement: True only for one plain command on the
    read-only list (git only with a reading subcommand and no --output,
    find without -exec / -delete / -fprint, date without -s), nothing
    joined, redirected, expanded or globbed (no ; & | ` < > $ * ? [ ] { }
    or newline), and every path it names -- and the working directory --
    readable (`readable(path)`: Folder access says yes without asking).
    Anything else is a question on a card, never a refusal."""
    command = str(command or "").strip()
    if not command or _SHELL_SIGNS.search(command):
        return False
    try:
        words = shlex.split(command)
    except ValueError:
        return False
    if not words or words[0] not in SAFE_COMMANDS:
        return False
    if words[0] == "git":
        rest = [w for w in words[1:] if not w.startswith("-")]
        if not rest or rest[0] not in SAFE_GIT:
            return False
        if any(w.startswith(("--output", "-o", "--ext-diff", "--textconv", "-c", "--exec")) for w in words):
            return False
    if words[0] == "find" and any(w in UNSAFE_FIND for w in words):
        return False
    if words[0] == "date" and any(w.startswith(("-s", "--set")) for w in words[1:]):
        return False
    if not readable(cwd):
        return False
    for w in words[1:]:
        if w.startswith("-") and "=" not in w:
            continue
        w = w.split("=", 1)[1] if w.startswith("-") else w
        if "/" in w or w.startswith("~") or w in (".", "..") or os.path.lexists(os.path.join(cwd, w)):
            if not readable(resolve(w, cwd)):
                return False
    return True


def policy(mode, name, args, cwd, readable=lambda path: False):
    """What happens to a tool call before it runs: "allow" (it runs),
    "ask" (a card), or "refuse" (the model is told why, nothing runs).
    Reading tools always "allow" here: Folder access decides about them
    when they run. The modes: the module docstring."""
    if name in READ_TOOLS:
        return "allow"
    if name not in CHANGE_TOOLS:
        return "refuse"
    if mode == "plan":
        return "refuse"
    if mode == "acceptEdits" and name in EDIT_TOOLS:
        target = resolve((args or {}).get("path"), cwd)
        return "allow" if cwd and under(target, os.path.normpath(cwd)) else "ask"
    if mode == "auto" and name == "run_command":
        return "allow" if safe_command((args or {}).get("command"), cwd, readable) else "ask"
    return "ask"


class ToolContext:
    """What a tool needs: the working directory, Folder access's answers
    for this conversation (session) and the folders open without asking
    (implied), whether to prompt at all, the run's cancel flag and a place
    to put a command's process (so Esc reaches it)."""

    def __init__(self, cwd, session=None, implied=(), prompt=True, reason=""):
        self.cwd = cwd
        self.session = session
        self.implied = list(implied)
        self.prompt = prompt
        self.reason = reason
        self.cancelled = threading.Event()
        self.proc = None
        self.on_proc = None

    def refused(self, path):
        if folder_access is None:
            return None
        try:
            return folder_access.refused(path)
        except Exception:       # noqa: BLE001
            return "could not be checked"

    def readable_now(self, path):
        """Folder access says yes without asking (Auto mode's test)."""
        if folder_access is None:
            return False
        try:
            return folder_access.decide(path, WHO, self.implied, self.session)[0] == "allow"
        except Exception:       # noqa: BLE001
            return False

    def may_read(self, path, why=""):
        """(ok, reason): Folder access, prompting when it has to (blocking:
        this is the run's thread)."""
        if folder_access is None:
            return False, "folder_access.py is missing: nothing is read"
        try:
            return folder_access.request(path, WHO, why or self.reason, implied=self.implied,
                                         session=self.session, prompt=self.prompt)
        except Exception as exc:    # noqa: BLE001
            return False, f"Folder access failed: {exc}"


class ToolError(Exception):
    pass


def t_read_file(args, ctx):
    path = resolve(args.get("path"), ctx.cwd)
    why = ctx.refused(path)
    if why:
        raise ToolError(f"{path}: {why}")
    if not os.path.isfile(path):
        raise ToolError(f"there is no file {path}" + (" (it is a folder: use list_dir)" if os.path.isdir(path) else ""))
    ok, why = ctx.may_read(path)
    if not ok:
        raise ToolError(why)
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as handle:
            raw = handle.read(READ_MAX)
    except OSError as exc:
        raise ToolError(exc.strerror or str(exc)) from None
    if b"\0" in raw[:4096]:
        raise ToolError(f"{path} is a binary file: not read")
    lines = raw.decode("utf-8", "replace").splitlines()
    try:
        start = max(1, int(args.get("offset") or 1))
    except (TypeError, ValueError):
        start = 1
    try:
        count = int(args.get("limit")) if args.get("limit") else len(lines)
    except (TypeError, ValueError):
        count = len(lines)
    shown = lines[start - 1:start - 1 + max(1, count)]
    out = "\n".join(f"{n:6}\t{line}" for n, line in enumerate(shown, start))
    if size > READ_MAX:
        out += f"\n[only the first {READ_MAX // 1024} KB of {size // 1024} KB were read]"
    return out or "(empty file)"


def t_list_dir(args, ctx):
    path = resolve(args.get("path") or ".", ctx.cwd)
    why = ctx.refused(path)
    if why:
        raise ToolError(f"{path}: {why}")
    if not os.path.isdir(path):
        raise ToolError(f"there is no folder {path}")
    ok, why = ctx.may_read(path)
    if not ok:
        raise ToolError(why)
    try:
        entries = sorted(os.scandir(path), key=lambda e: (not e.is_dir(), e.name.lower()))
    except OSError as exc:
        raise ToolError(exc.strerror or str(exc)) from None
    rows = [e.name + ("/" if e.is_dir() else "") for e in entries[:LIST_MAX]]
    if len(entries) > LIST_MAX:
        rows.append(f"[... {len(entries) - LIST_MAX} more]")
    return f"{path}:\n" + ("\n".join(rows) if rows else "(empty)")


def t_search(args, ctx):
    pattern, glob = args.get("pattern") or "", args.get("glob") or ""
    if not pattern and not glob:
        raise ToolError("give a pattern (contents) or a glob (file names), or both")
    root = resolve(args.get("path") or ".", ctx.cwd)
    why = ctx.refused(root)
    if why:
        raise ToolError(f"{root}: {why}")
    if not os.path.exists(root):
        raise ToolError(f"there is no {root}")
    ok, why = ctx.may_read(root)
    if not ok:
        raise ToolError(why)
    try:
        rx = re.compile(pattern) if pattern else None
    except re.error as exc:
        raise ToolError(f"not a valid regular expression: {exc}") from None
    files = [root] if os.path.isfile(root) else []
    if not files:
        for top, dirs, names in os.walk(root):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
            for name in sorted(names):
                files.append(os.path.join(top, name))
            if len(files) >= SEARCH_FILES or ctx.cancelled.is_set():
                break
    hits, seen = [], 0
    for path in files[:SEARCH_FILES]:
        if ctx.cancelled.is_set():
            break
        if glob and not (fnmatch.fnmatch(os.path.basename(path), glob)
                         or fnmatch.fnmatch(os.path.relpath(path, root), glob)):
            continue
        if ctx.refused(path):
            continue
        shown = os.path.relpath(path, ctx.cwd) if under(path, ctx.cwd) else path
        if rx is None:
            hits.append(shown)
        else:
            try:
                if os.path.getsize(path) > SEARCH_FILE_MAX:
                    continue
                with open(path, "rb") as handle:
                    raw = handle.read()
            except OSError:
                continue
            if b"\0" in raw[:4096]:
                continue
            seen += 1
            for n, line in enumerate(raw.decode("utf-8", "replace").splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{shown}:{n}: {line[:300]}")
                    if len(hits) >= SEARCH_HITS:
                        break
        if len(hits) >= SEARCH_HITS:
            break
    if not hits:
        return "no matches"
    more = f"\n[stopped at {SEARCH_HITS} matches]" if len(hits) >= SEARCH_HITS else ""
    return "\n".join(hits) + more


def t_run_command(args, ctx):
    command = str(args.get("command") or "").strip()
    if not command:
        raise ToolError("no command given")
    try:
        limit = min(TIMEOUT_MAX, max(1, int(args.get("timeout") or TIMEOUT_S)))
    except (TypeError, ValueError):
        limit = TIMEOUT_S
    env = dict(os.environ, TERM="dumb", PAGER="cat", GIT_PAGER="cat", NO_COLOR="1")
    with tempfile.TemporaryFile() as out:
        try:
            proc = subprocess.Popen(["bash", "-c", command], cwd=ctx.cwd, env=env, stdin=subprocess.DEVNULL,
                                    stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
        except OSError as exc:
            raise ToolError(f"could not start bash: {exc}") from None
        ctx.proc = proc
        if ctx.on_proc:
            ctx.on_proc(proc.pid)
        deadline = time.monotonic() + limit
        why = None
        while True:
            try:
                proc.wait(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                pass
            if ctx.cancelled.is_set():
                why = "stopped by the user"
            elif time.monotonic() > deadline:
                why = f"stopped after {limit} s (timeout)"
            if why:
                _kill_group(proc)
                break
        ctx.proc = None
        out.seek(0)
        text = out.read(4 * OUTPUT_MAX + 1).decode("utf-8", "replace")
    text = re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]", "", text)
    if len(text) > 4 * OUTPUT_MAX:
        text = text[:4 * OUTPUT_MAX] + "\n[... output cut ...]"
    code = proc.returncode
    tail = f"\n[{why}]" if why else (f"\n[exit code {code}]" if code else "")
    if why or code:
        raise ToolError((text.rstrip() + tail).strip())
    return text.rstrip() or "(no output)"


def _kill_group(proc):
    for sig, wait in ((signal.SIGTERM, 1.5), (signal.SIGKILL, 2)):
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            return
        try:
            proc.wait(timeout=wait)
            return
        except subprocess.TimeoutExpired:
            continue


def _writable(path, ctx):
    why = ctx.refused(path)
    if why:
        raise ToolError(f"{path}: {why} -- not written either")


def t_write_file(args, ctx):
    path = resolve(args.get("path"), ctx.cwd)
    _writable(path, ctx)
    if os.path.isdir(path):
        raise ToolError(f"{path} is a folder")
    content = str(args.get("content") if args.get("content") is not None else "")
    existed = os.path.exists(path)
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        _atomic_write(path, content)
    except OSError as exc:
        raise ToolError(exc.strerror or str(exc)) from None
    return (f"{'replaced' if existed else 'created'} {path}: {len(content.splitlines())} lines, "
            f"{len(content.encode())} bytes")


def t_edit_file(args, ctx):
    path = resolve(args.get("path"), ctx.cwd)
    _writable(path, ctx)
    old, new = str(args.get("old_string") or ""), str(args.get("new_string") or "")
    if not old:
        raise ToolError("old_string is empty: use write_file for a new file")
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except FileNotFoundError:
        raise ToolError(f"there is no file {path}") from None
    except (OSError, UnicodeDecodeError) as exc:
        raise ToolError(f"could not read {path}: {exc}") from None
    n = text.count(old)
    if n == 0:
        raise ToolError(f"old_string is not in {path}: nothing changed (read the file and copy the text exactly)")
    if n > 1 and not args.get("replace_all"):
        raise ToolError(f"old_string is in {path} {n} times: nothing changed (add surrounding lines to make it "
                        "unique, or set replace_all)")
    try:
        _atomic_write(path, text.replace(old, new) if args.get("replace_all") else text.replace(old, new, 1))
    except OSError as exc:
        raise ToolError(exc.strerror or str(exc)) from None
    return f"edited {path}: {n if args.get('replace_all') else 1} replacement{'s' if n > 1 and args.get('replace_all') else ''}"


def _atomic_write(path, text):
    folder = os.path.dirname(path) or "."
    mode = None
    try:
        mode = os.stat(path).st_mode & 0o7777
    except OSError:
        pass
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".llm-chat-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


RUNNERS = {"read_file": t_read_file, "list_dir": t_list_dir, "search": t_search,
           "run_command": t_run_command, "write_file": t_write_file, "edit_file": t_edit_file}


def run_tool(name, args, ctx):
    """(output, is_error), the output clipped."""
    runner = RUNNERS.get(name)
    if runner is None:
        return f"there is no tool {name!r}: the tools are {', '.join(TOOL_NAMES)}", True
    try:
        return clip(runner(args if isinstance(args, dict) else {}, ctx)), False
    except ToolError as exc:
        return clip(str(exc)), True
    except Exception as exc:        # noqa: BLE001 -- a tool's surprise is the model's error to read
        return f"{name} failed: {type(exc).__name__}: {exc}", True


# -- one message --------------------------------------------------------------------------------
def system_prompt(cwd, mode, tools=True):
    today = datetime.datetime.now().strftime("%A %Y-%m-%d %H:%M")
    text = (f"You are a helpful assistant in a chat window on the user's Linux desktop. Today is {today}. "
            f"The working directory is {cwd}. Answer in the user's language; Markdown is rendered.")
    if tools:
        text += (" You have tools to read files, list folders, search, run shell commands and write or edit "
                 "files; paths are relative to the working directory. Use them when the task needs them, "
                 "not otherwise. The user may deny a tool call: then respect that and do not retry it.")
        if mode == "plan":
            text += (" PLAN MODE: only reading tools are available. Investigate, then propose a plan; "
                     "change nothing.")
    return text


def user_message(text, images=()):
    """A user message: plain words, or parts (the images as data: URIs,
    then the words). images: [{"media", "data"}] (window attachments)."""
    if not images:
        return {"role": "user", "content": text}
    parts = [{"type": "image_url", "image_url": {
        "url": f"data:{a['media']};base64,{base64.b64encode(a['data']).decode()}"}} for a in images]
    if text:
        parts.append({"type": "text", "text": text})
    return {"role": "user", "content": parts}


def no_tool_support(exc, images=False):
    """Does this error mean "no function calling here"? Said so (tools,
    function calling, llama-server's --jinja), or -- with no picture in the
    request and nothing about the context's size -- a 400 / 404 / 422 / 500
    / 501 to a request that had tools in it. 401 / 403 / 429 never."""
    text = (exc.message or "").lower()
    if exc.status in (401, 403, 429) or re.search(r"context|too long|token", text):
        return False
    if re.search(r"\btools?\b|function.?call|jinja", text):
        return True
    return not images and exc.status in (400, 404, 422, 500, 501)


def has_images(messages):
    return any(isinstance(m.get("content"), list) and any(
        isinstance(p, dict) and p.get("type") == "image_url" for p in m["content"]) for m in messages)


class Run:
    """One message's whole turn, in a thread: the request, its stream, the
    tools it calls, again, until an answer. `emit(kind, data)` is called
    from that thread (the window hands each to the GTK loop) with:

        start      {"step"}                  a request goes out
        text       {"text"}                  reply words, as they come
        reasoning  {"text"}                  thinking words, as they come
        tool       {"id", "name", "canon", "input"}     a call begins
        tool_done  {"id", "output", "is_error"}
        ask        {"req"}                   a yes is needed: answer(req id, ...)
        pgid       {"pgid"}                  a command's process group
        no_tools   {"why"}                   the model takes no tools: plain chat
        usage      {"prompt", "completion"}
        done       {"ok", "stopped", "error", "messages", "steps", "seconds",
                    "usage", "tools"}

    `messages` is the conversation so far plus the new user message (the
    system prompt is added per request, never kept). The finished
    conversation comes back in "done"."""

    def __init__(self, ep, model, messages, emit, mode="ask", cwd=None, tools=True,
                 max_steps=MAX_STEPS, session=None, implied=(), prompt=True, extra=None):
        self.ep, self.model, self.emit = ep, model, emit
        self.mode, self.cwd = mode, cwd or os.path.expanduser("~")
        self.messages = list(messages)
        self.start_len = len(self.messages)
        self.tools_on = bool(tools)
        self.max_steps = max_steps
        self.extra = dict(extra or {})
        asked = message_words(self.messages[-1].get("content")) if self.messages else ""
        self.ctx = ToolContext(self.cwd, session, implied, prompt,
                               reason=f"to answer “{' '.join(asked.split())[:140]}”" if asked else "")
        self.partial = []           # the reply streamed so far in the current request
        self.ctx.on_proc = lambda pgid: self.emit("pgid", {"pgid": pgid})
        self.holder = {}
        self.waiting = {}           # req id -> [Event, answer]
        self.lock = threading.Lock()
        self.thread = None
        self.usage = None
        self.steps = 0

    # -- the window's side
    def start(self):
        self.thread = threading.Thread(target=self._main, daemon=True)
        self.thread.start()
        return self

    def cancel(self):
        """Esc: the stream cut, a running command's group ended, every open
        question a no. The thread then ends with done(stopped)."""
        self.holder["cancel"] = True
        self.ctx.cancelled.set()
        sock = self.holder.get("sock")
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        proc = self.ctx.proc
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
        with self.lock:
            for event, box in self.waiting.values():
                box.append(("deny", "stopped"))
                event.set()

    def answer(self, rid, allow, note=""):
        """A card's answer; False when nobody waits for it any more."""
        with self.lock:
            entry = self.waiting.get(rid)
            if entry is None:
                return False
            entry[1].append(("allow" if allow else "deny", note or ""))
            entry[0].set()
        return True

    @property
    def cancelled(self):
        return self.ctx.cancelled.is_set()

    # -- the thread
    def _ask(self, req):
        event, box = threading.Event(), []
        with self.lock:
            if self.cancelled:
                return "deny", "stopped"
            self.waiting[req["id"]] = (event, box)
        self.emit("ask", {"req": req})
        event.wait()
        with self.lock:
            self.waiting.pop(req["id"], None)
        return box[0] if box else ("deny", "")

    def _main(self):
        started = time.monotonic()
        error, ok = None, False
        try:
            self._loop()
            ok = not self.cancelled
        except Cancelled:
            pass
        except ServerError as exc:
            error = exc.message if exc.status is None else f"the server said {exc.status}: {exc.message}"
            if has_images(self.messages[self.start_len - 1:self.start_len]):
                error += (f"\n{self.model} may not see images: pick a vision model (Ctrl+M), or send it "
                          "without the picture")
        except Exception as exc:        # noqa: BLE001 -- said in the window, never a dead thread
            error = f"{type(exc).__name__}: {exc}"
        stopped = self.cancelled
        if (error or stopped) and len(self.messages) == self.start_len:
            # Nothing came back for it: the message is not kept (an image a
            # model refuses would be refused again with every next one).
            self.messages = self.messages[:self.start_len - 1]
        self.emit("done", {"ok": ok and not error, "stopped": stopped, "error": error,
                           "messages": self.messages, "steps": self.steps,
                           "seconds": time.monotonic() - started, "usage": self.usage,
                           "tools": self.tools_on})

    def _request(self, step, last):
        system = {"role": "system", "content": system_prompt(self.cwd, self.mode, self.tools_on and not last)}
        msgs = [system] + self.messages
        if last and self.tools_on:
            msgs.append({"role": "user", "content": "(The step limit is reached: answer now with what you "
                                                    "have, without tools.)"})
        body = {"model": self.model, "messages": msgs, "stream_options": {"include_usage": True}, **self.extra}
        if self.tools_on and not last:
            body["tools"] = tool_specs(self.mode)
        return body

    def _one(self, body):
        """One streamed request: (text, calls, finish), emitting as it goes."""
        text, calls, finish = self.partial, {}, None
        text.clear()
        split = ThinkSplitter()
        for chunk in stream(self.ep, body, self.holder):
            if isinstance(chunk.get("usage"), dict):
                u = chunk["usage"]
                self.usage = {"prompt": u.get("prompt_tokens") or 0, "completion": u.get("completion_tokens") or 0}
                self.emit("usage", dict(self.usage))
            for choice in chunk.get("choices") or []:
                delta = choice.get("delta") or {}
                think = delta.get("reasoning_content") or delta.get("reasoning")
                if isinstance(think, str) and think:
                    self.emit("reasoning", {"text": think})
                piece = delta.get("content")
                if isinstance(piece, str) and piece:
                    words, inline = split.feed(piece)
                    if inline:
                        self.emit("reasoning", {"text": inline})
                    if words:
                        text.append(words)
                        self.emit("text", {"text": words})
                for tc in delta.get("tool_calls") or []:
                    if not isinstance(tc, dict):
                        continue
                    slot = calls.setdefault(tc.get("index", len(calls)), {"id": "", "name": "", "args": ""})
                    slot["id"] = tc.get("id") or slot["id"]
                    fn = tc.get("function") or {}
                    slot["name"] += fn.get("name") or ""
                    args = fn.get("arguments")
                    if isinstance(args, dict):
                        slot["args"] = json.dumps(args)
                    elif isinstance(args, str):
                        slot["args"] += args
                finish = choice.get("finish_reason") or finish
        words, inline = split.flush()
        if inline:
            self.emit("reasoning", {"text": inline})
        if words:
            text.append(words)
            self.emit("text", {"text": words})
        return "".join(text), [calls[k] for k in sorted(calls)], finish

    def _loop(self):
        step = 0
        while step <= self.max_steps:
            if self.cancelled:
                raise Cancelled()
            last = step == self.max_steps
            self.emit("start", {"step": step})
            body = self._request(step, last)
            try:
                text, calls, _finish = self._one(body)
            except Cancelled:
                if "".join(self.partial).strip():       # what was on screen stays said
                    self.messages.append({"role": "assistant", "content": "".join(self.partial)})
                raise
            except ServerError as exc:
                if "tools" in body and not self.partial and no_tool_support(exc, has_images(body["messages"])):
                    # No function calling here: the same again, plain chat.
                    self.tools_on = False
                    self.emit("no_tools", {"why": exc.message})
                    continue
                raise
            self.steps = step + 1
            msg = {"role": "assistant", "content": text}
            calls = [c for c in calls if c["name"]]
            if calls:
                for n, c in enumerate(calls):
                    c["id"] = c["id"] or f"call_{uuid.uuid4().hex[:12]}_{n}"
                msg["tool_calls"] = [{"id": c["id"], "type": "function",
                                      "function": {"name": c["name"], "arguments": c["args"] or "{}"}}
                                     for c in calls]
            if self.cancelled and not calls:
                if text:
                    self.messages.append(msg)
                raise Cancelled()
            self.messages.append(msg)
            if not calls:
                return
            for c in calls:
                if self.cancelled:
                    out, bad = "stopped by the user before it ran", True
                else:
                    out, bad = self._call(c)
                self.messages.append({"role": "tool", "tool_call_id": c["id"], "content": out})
            step += 1

    def _call(self, c):
        name = c["name"]
        try:
            args = json.loads(c["args"] or "{}")
            if not isinstance(args, dict):
                raise ValueError("not an object")
        except ValueError as exc:
            self.emit("tool", {"id": c["id"], "name": name, "canon": name, "input": {}})
            out = f"the arguments were not valid JSON ({exc}): {c['args'][:200]}"
            self.emit("tool_done", {"id": c["id"], "output": out, "is_error": True})
            return out, True
        cname, cinput = canon(name, args)
        self.emit("tool", {"id": c["id"], "name": name, "canon": cname, "input": cinput})
        verdict = policy(self.mode, name, args, self.cwd, self.ctx.readable_now)
        if verdict == "refuse":
            out = (f"{name} is not available in plan mode (read-only): propose the change instead"
                   if self.mode == "plan" and name in CHANGE_TOOLS
                   else f"there is no tool {name!r}: the tools are {', '.join(TOOL_NAMES)}")
            bad = True
        else:
            if verdict == "ask":
                req = {"id": uuid.uuid4().hex, "tool": cname, "display": name, "input": cinput,
                       "suggestions": [], "blocked": None, "reason": None, "tool_use_id": c["id"],
                       "agent": None, "native": True}
                answer, note = self._ask(req)
                if answer != "allow":
                    out = "stopped by the user" if note == "stopped" and self.cancelled else deny_message(note)
                    self.emit("tool_done", {"id": c["id"], "output": out, "is_error": True})
                    return out, True
            out, bad = run_tool(name, args, self.ctx)
        self.emit("tool_done", {"id": c["id"], "output": out, "is_error": bad})
        return out, bad


# -- sessions -------------------------------------------------------------------------------------
_ID = re.compile(r"^chat-\d{8}-\d{6}-[0-9a-f]{6}$")


def new_session_id():
    return time.strftime("chat-%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]


def is_session_id(text):
    return bool(_ID.match(str(text or "")))


def session_path(sid, folder=None):
    return os.path.join(folder or SESSIONS, sid + ".json")


def _stored(messages):
    """The messages as written: an image part becomes "[image]"."""
    out = []
    for m in messages:
        if isinstance(m.get("content"), list):
            parts = []
            for p in m["content"]:
                if isinstance(p, dict) and p.get("type") == "image_url":
                    parts.append({"type": "text", "text": "[image]"})
                elif isinstance(p, dict):
                    parts.append(p)
            m = dict(m, content=parts)
        out.append(m)
    return out


def message_words(content):
    """The words of a message's content (parts joined, an image "🖼 image")."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        bits = []
        for p in content:
            if isinstance(p, dict) and p.get("type") == "text":
                bits.append("🖼 image" if p.get("text") == "[image]" else str(p.get("text") or ""))
            elif isinstance(p, dict) and p.get("type") == "image_url":
                bits.append("🖼 image")
        return "\n".join(b for b in bits if b)
    return ""


def save_session(sid, messages, cwd, model, folder=None):
    folder = folder or SESSIONS
    os.makedirs(folder, mode=0o700, exist_ok=True)
    path = session_path(sid, folder)
    try:
        with open(path) as handle:
            old = json.load(handle)
    except (OSError, ValueError):
        old = {}
    first = next((message_words(m.get("content")) for m in messages if m.get("role") == "user"), "")
    data = {"id": sid, "title": " ".join(first.split())[:200] or old.get("title") or "(no words)",
            "cwd": cwd, "model": model, "created": old.get("created") or time.time(), "updated": time.time(),
            "messages": _stored(messages)}
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".tmp-")
    with os.fdopen(fd, "w") as handle:
        json.dump(data, handle, ensure_ascii=False)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return path


def load_session(sid_or_path, folder=None):
    path = sid_or_path if os.sep in str(sid_or_path) else session_path(sid_or_path, folder)
    with open(path) as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or not isinstance(data.get("messages"), list):
        raise ValueError("not a chat session")
    return data


def list_sessions(limit=15, folder=None):
    """[{"id", "path", "mtime", "cwd", "title", "model"}], newest first."""
    folder = folder or SESSIONS
    try:
        files = [(e.stat().st_mtime, e.path) for e in os.scandir(folder)
                 if e.name.endswith(".json") and is_session_id(e.name[:-5])]
    except OSError:
        return []
    out = []
    for mtime, path in sorted(files, reverse=True)[:limit]:
        try:
            data = load_session(path)
        except (OSError, ValueError):
            continue
        out.append({"id": data.get("id") or os.path.basename(path)[:-5], "path": path, "mtime": mtime,
                    "cwd": data.get("cwd"), "title": data.get("title") or "(no words)",
                    "model": data.get("model"), "kind": "native"})
    return out


def delete_session(path):
    if not is_session_id(os.path.basename(path)[:-5]):
        return False
    try:
        os.remove(path)
        return True
    except OSError:
        return False
