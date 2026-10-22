#!/usr/bin/env python3
"""Ask your desktop: questions about your own files, clipboard and what you
were doing, answered by a LOCAL model (LM Studio) -- nothing leaves the
machine.

    ask-desktop.py "what was I working on yesterday at 3pm"
    ask-desktop.py "find the PDF about invoices from last week"
    ask-desktop.py --json "..."      {"answer": ..., "files": [paths]}
    ask-desktop.py --notify "..."    the answer as a notification ("Asking..."
                                     first), with an Open button for up to
                                     three of the files it points to (the
                                     launcher's "ask ..." runs this)

The model gets three tools and the date and time now:

    search_activity(start, end, text?)   which windows had the focus then
                                         (activity-log.py's log), as time
                                         per app and per window title
    search_files(query?, modified_after?, modified_before?, extension?)
                                         plocate by name under $HOME (no
                                         hidden folders), filtered by date;
                                         with no name, the newest files in
                                         Documents / Downloads / Desktop...
                                         For the top PDFs and text files, the
                                         first lines of their text
    search_clipboard(query)              text entries of the clipboard
                                         history (cliphist), newest first
    search_meaning(query, k?)            the pieces of your documents that
                                         are ABOUT that, with their path and
                                         a snippet (desktop-index.py's index
                                         of ~/Documents, ~/Downloads,
                                         ~/Desktop and the repos in your
                                         projects folder);
                                         only offered when the index exists
                                         and Privacy's search index is on
    search_memory(query, start?, end?, source?)
                                         desktop-memory.py: what went past,
                                         with its time -- window titles,
                                         copies, notifications, captions,
                                         screenshots' text -- with links and
                                         thumbnails; only offered when Desktop
                                         memory is on and has something

A model that does not call tools (or a server that refuses them) gets the
fallback: the searches run here on the words and the time words of the
question ("yesterday", "last week", "at 3pm") -- search_meaning on the
whole question -- and the model only reads the results.

Settings > Privacy decides whether it answers at all and which of the three
sources it may read (privacy.conf ask / ask_files / ask_clipboard /
ask_activity, and ask_index for search_meaning, which also needs ask_files;
see privacy_settings.py): a source that is off is not offered
to the model, is skipped by the fallback, and a call to it anyway gets
"turned off" instead of results. With Ask off, every question gets a short
"turned off" answer and no model is started. search_memory follows Desktop
memory's own switches (privacy.conf memory / memory_<source>): only the
sources that are on are searched.

Folder access (folder_access.py, Settings > Privacy > Folder access): the
searches may find any file their switches allow -- names, dates, which
documents match -- but the TEXT of a file (search_files' first lines,
search_meaning's snippets) reaches the model only when its folder is open
to the asker (who: "ask-desktop" here; the assistant passes its own, and
"phone"). The rest come back without their text and with a "withheld"
note naming the folders, so the model can say so. Nothing here prompts: a
search touches many folders at once, and one question must not open a
stack of dialogs (the assistant's read_file asks, one file at a time).

Model: the launcher's "quick" model if that is a local one, else its
"default" if local, else the first local model (llm_models.py) -- loaded
through llm_models.ensure_local, so LM Studio starts if it has to.
"""
import datetime
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import importlib.util
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import desktop_conf  # noqa: E402  (your projects folder)
import folder_access  # noqa: E402  (which folders' text the model may see)
import llm_models  # noqa: E402
import privacy_settings  # noqa: E402  (privacy.conf: on / off and the sources)

# desktop-index.py has a dash in its name: imported by path.
_spec = importlib.util.spec_from_file_location("desktop_index", os.path.join(HERE, "desktop-index.py"))
desktop_index = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(desktop_index)
sys.modules.setdefault("desktop_index", desktop_index)
_spec = importlib.util.spec_from_file_location("desktop_memory", os.path.join(HERE, "desktop-memory.py"))
desktop_memory = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(desktop_memory)

HOME = os.path.expanduser("~")
ACTIVITY = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.join(HOME, ".local", "state"),
                        "hypr", "activity.jsonl")
# Under home, the last one absolute: your projects folder (desktop.conf)
# -- os.path.join(HOME, an absolute path) is that path.
BROWSE_DIRS = ["Documents", "Downloads", "Desktop", "Pictures", "Videos", "Music",
               desktop_conf.projects_dir()]
MAX_FILES = 25
PEEK_FILES = 5              # the top hits whose text the model also gets
PEEK_CHARS = 400
MAX_CLIPS = 15
MEANING_K = 8               # pieces search_meaning returns by default (at most 15)
MAX_ROUNDS = 5
CALL_TIMEOUT = 180          # s per model call (a cold 27B is slow)
TEXT_EXT = {".txt", ".md", ".py", ".sh", ".lua", ".conf", ".json", ".csv", ".log", ".ini", ".toml", ".yaml", ".yml"}
STOP = set("the a an of to in on at for from about and or my me i was were is are what which when "
           "where who find show open did do does last this that these those yesterday today week "
           "month ago pm am file files pdf document documents working work".split())

TOOLS = [
    {"type": "function", "function": {
        "name": "search_activity",
        "description": "Which windows had the keyboard focus in a time range: time spent per app "
                       "and per window title, and the order. Use for 'what was I doing / working on'.",
        "parameters": {"type": "object", "properties": {
            "start": {"type": "string", "description": "ISO local date-time, e.g. 2026-10-19T14:30"},
            "end": {"type": "string", "description": "ISO local date-time"},
            "text": {"type": "string", "description": "optional: only windows whose app or title has this"}},
            "required": ["start", "end"]}}},
    {"type": "function", "function": {
        "name": "search_files",
        "description": "Find files in the home folder by name words and/or modification date. "
                       "Returns paths, dates, sizes and the first text of the top documents.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "words that must all be in the path (optional)"},
            "modified_after": {"type": "string", "description": "ISO local date-time (optional)"},
            "modified_before": {"type": "string", "description": "ISO local date-time (optional)"},
            "extension": {"type": "string", "description": "e.g. pdf, png, docx (optional)"}}}}},
    {"type": "function", "function": {
        "name": "search_clipboard",
        "description": "Search the text entries of the clipboard history, newest first.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "words to look for"}},
            "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "search_meaning",
        "description": "Search INSIDE the user's documents, notes, PDFs and code by meaning: returns the "
                       "best-matching passages with their file path and a snippet. Use it when the "
                       "question is about a topic or what a file says, not its name or date.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "what the passage should be about, in plain words"},
            "k": {"type": "integer", "description": "how many passages (default 8, at most 15)"}},
            "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "search_memory",
        "description": "Search the desktop memory: what went past on the screen with its time -- window "
                       "titles, copied text, notifications, live-caption text, screenshot text -- with "
                       "links. Use it for 'when did I last see / what link did someone send / what was "
                       "that error' questions. Time words in the query work too ('yesterday', 'el martes').",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "what it was about, in plain words"},
            "start": {"type": "string", "description": "ISO local date-time (optional)"},
            "end": {"type": "string", "description": "ISO local date-time (optional)"},
            "source": {"type": "string", "description": "optional: activity, clipboard, notifications, "
                                                        "captions or screen"}},
            "required": ["query"]}}},
]


# -- the searches -----------------------------------------------------------------
def parse_time(value, default):
    if not value:
        return default
    try:
        return datetime.datetime.fromisoformat(str(value).replace("Z", "")).timestamp()
    except ValueError:
        return default


def human(seconds):
    m = int(seconds // 60)
    return f"{m // 60} h {m % 60} min" if m >= 60 else f"{max(m, 1)} min"


def search_activity(start=None, end=None, text=None):
    now = time.time()
    t0, t1 = parse_time(start, now - 86400), parse_time(end, now)
    try:
        with open(ACTIVITY) as handle:
            rows = [json.loads(line) for line in handle if line.strip()]
    except (OSError, ValueError):
        rows = []
    if not rows:
        return {"note": "the activity log is empty (activity-log.service started recently)"}
    periods = []
    for i, row in enumerate(rows):
        a = row["t"]
        b = rows[i + 1]["t"] if i + 1 < len(rows) else now
        a, b = max(a, t0), min(b, t1)
        if b > a and row.get("class"):
            periods.append((a, b, row))
    if text:
        low = text.lower()
        periods = [p for p in periods if low in (p[2].get("class", "") + " " + p[2].get("title", "")).lower()]
    if not periods:
        first = datetime.datetime.fromtimestamp(rows[0]["t"]).isoformat(timespec="minutes")
        return {"note": f"nothing logged in that range (the log starts at {first})"}
    per_app, per_title = {}, {}
    for a, b, row in periods:
        per_app[row["class"]] = per_app.get(row["class"], 0) + b - a
        key = (row["class"], row.get("title", ""))
        per_title[key] = per_title.get(key, 0) + b - a
    timeline = []
    for a, b, row in periods:
        if b - a >= 60:
            timeline.append(f"{datetime.datetime.fromtimestamp(a):%a %H:%M}-"
                            f"{datetime.datetime.fromtimestamp(b):%H:%M}  {row['class']}: {row.get('title', '')[:90]}")
    return {
        "apps": [f"{c}: {human(s)}" for c, s in sorted(per_app.items(), key=lambda kv: -kv[1])[:10]],
        "windows": [f"{c}: {t[:100]}  ({human(s)})" for (c, t), s in
                    sorted(per_title.items(), key=lambda kv: -kv[1])[:20]],
        "timeline": timeline[:40],
    }


def peek(path):
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".pdf":
            out = subprocess.run(["pdftotext", "-l", "2", path, "-"], capture_output=True,
                                 text=True, timeout=8).stdout
        elif ext in TEXT_EXT and os.path.getsize(path) < 5_000_000:
            with open(path, errors="replace") as handle:
                out = handle.read(PEEK_CHARS * 2)
        else:
            return None
    except (OSError, subprocess.SubprocessError):
        return None
    return " ".join(out.split())[:PEEK_CHARS] or None


def visible(path):
    rel = os.path.relpath(path, HOME)
    return not rel.startswith("..") and not any(part.startswith(".") for part in rel.split(os.sep))


def search_files(query=None, modified_after=None, modified_before=None, extension=None, may_read=None):
    """`may_read(path)`: may the first lines of this file be given (None:
    yes) -- call_search() hands in the folder-access check."""
    t0 = parse_time(modified_after, 0)
    t1 = parse_time(modified_before, time.time() + 86400)
    ext = ("." + extension.lower().lstrip(".")) if extension else None
    words = [w for w in re.findall(r"[\w\-]+", (query or "").lower()) if w]
    paths = []
    if words:
        try:
            # The home folder as one more pattern: -l counts before any
            # filter here, and the system's own paths would use it all up.
            out = subprocess.run(["plocate", "-i", "-l", "50000", HOME + os.sep, *words],
                                 capture_output=True, text=True, timeout=10).stdout
            paths = [p for p in out.splitlines() if p.startswith(HOME + os.sep)]
        except (OSError, subprocess.SubprocessError):
            paths = []
    else:
        for top in BROWSE_DIRS:
            for root, dirs, files in os.walk(os.path.join(HOME, top)):
                dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "__pycache__")]
                paths += [os.path.join(root, f) for f in files if not f.startswith(".")]
                if len(paths) > 50000:
                    break
    found = []
    for p in paths:
        if not visible(p) or (ext and not p.lower().endswith(ext)):
            continue
        # plocate matches anywhere in the path; a hit only in a folder name
        # far up is weak, but still a hit.
        try:
            st = os.stat(p)
        except OSError:
            continue
        if os.path.isdir(p) or not (t0 <= st.st_mtime <= t1):
            continue
        found.append((st.st_mtime, p, st.st_size))
    found.sort(reverse=True)
    results = []
    for i, (mtime, p, size) in enumerate(found[:MAX_FILES]):
        row = {"path": p, "modified": datetime.datetime.fromtimestamp(mtime).isoformat(timespec="minutes"),
               "size_kb": round(size / 1024)}
        if i < PEEK_FILES and (may_read is None or may_read(p)):
            text = peek(p)
            if text:
                row["text"] = text
        results.append(row)
    return {"count": len(found), "files": results}


def search_clipboard(query=""):
    try:
        out = subprocess.run(["cliphist", "list"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return {"note": "cliphist did not answer"}
    words = [w for w in (query or "").lower().split() if w]
    hits = []
    for line in out.splitlines():
        _, _, text = line.partition("\t")
        if text.startswith("[[ binary data"):
            continue
        if all(w in text.lower() for w in words):
            hits.append(text[:200])
        if len(hits) >= MAX_CLIPS:
            break
    return {"entries": hits}


def search_meaning(query="", k=MEANING_K):
    """desktop-index.py's search, shaped like the other tools: "files" (the
    paths, so the answer's Open buttons find them) with a snippet each."""
    try:
        k = max(1, min(15, int(k)))
    except (TypeError, ValueError):
        k = MEANING_K
    res = desktop_index.search(str(query or ""), k)
    if "note" in res:
        return {"note": res["note"]}
    return {"mode": res["mode"], "count": len(res["results"]),
            "files": [{"path": r["path"], "modified": r["modified"], "snippet": r["snippet"]}
                      for r in res["results"]]}


def index_ready(conf=None):
    """search_meaning may be offered: the switches allow it (ask, ask_files,
    ask_index) and there is an index to search."""
    return desktop_index.allowed(conf) and os.path.exists(desktop_index.DB)


def search_memory(query="", start=None, end=None, source=None):
    """desktop-memory.py's search: its time words count when no start / end
    is given. "files" holds the links and thumbnails (the Open buttons)."""
    if start or end:
        now = time.time()
        res = desktop_memory.search(str(query or ""), parse_time(start, None), parse_time(end, now),
                                    [source] if source else None)
    else:
        res = desktop_memory.search_words(str(query or ""), sources=[source] if source else None)
    if "note" in res:
        return {"note": res["note"]}
    rows = res["results"]
    for r in rows:
        r.pop("t", None)
    return {"mode": res["mode"], "range": res.get("range"), "memories": rows,
            "files": [{"path": r.get("url") or r.get("thumbnail")} for r in rows
                      if r.get("url") or r.get("thumbnail")]}


def memory_ready(conf=None):
    """search_memory may be offered: Ask and Desktop memory on, and a store."""
    conf = privacy_settings.load() if conf is None else conf
    return (privacy_settings.ask_on(conf) and bool(privacy_settings.memory_sources(conf))
            and os.path.exists(desktop_memory.DB))


SEARCHES = {"search_activity": search_activity, "search_files": search_files,
            "search_clipboard": search_clipboard, "search_meaning": search_meaning,
            "search_memory": search_memory}
SOURCE_OF = {"search_activity": "activity", "search_files": "files", "search_clipboard": "clipboard",
             "search_meaning": "index", "search_memory": "memory"}
OFF_NOTE = {"note": "the user turned this source off in Settings > Privacy; say so instead of guessing"}
OFF_ANSWER = "Ask your desktop is turned off (Settings > Privacy)."
NO_SOURCES = ("Ask your desktop may not read anything right now: files, clipboard and activity "
              "are all off in Settings > Privacy.")


def allowed_tools(sources):
    """`sources` is ask_sources(), plus "index" when index_ready()."""
    return [t for t in TOOLS if SOURCE_OF[t["function"]["name"]] in sources]


def content_allowed(path, who="ask-desktop", session=None):
    """May the text of this file reach the model (its folder is open to `who`)?"""
    try:
        return folder_access.check(path, who, session=session) == "allow"
    except (ValueError, OSError):
        return False


def withhold(result, who="ask-desktop", session=None):
    """A search's result without the text ("text", "snippet") of the files
    whose folders are not open to `who`, and a note that says which."""
    if not isinstance(result, dict):
        return result
    hidden = []
    for row in result.get("files") or []:
        if isinstance(row, dict) and row.get("path") and ("text" in row or "snippet" in row) \
                and not content_allowed(row["path"], who, session):
            row.pop("text", None)
            row.pop("snippet", None)
            hidden.append(folder_access.tilde(folder_access.folder_of(row["path"])))
    if hidden:
        result["withheld"] = (
            "the text of the files in " + ", ".join(dict.fromkeys(hidden)) + " is not shown: the user has not "
            "opened those folders to AI (Settings > Privacy > Folder access)"
            + ("; read_file asks them for one file" if who == "assistant" else "; tell them so"))
    return result


def call_search(name, args, sources, who="ask-desktop", session=None):
    """One tool call from the model, refused when its source is off; the
    files' text only from the folders open to `who` (withhold())."""
    if SOURCE_OF.get(name) not in sources:
        return dict(OFF_NOTE)
    if name == "search_files":
        args = dict(args, may_read=lambda p: content_allowed(p, who, session))
    return withhold(SEARCHES[name](**args), who, session)


# -- the fallback's own reading of the question --------------------------------------
def time_range(q, now):
    """(start, end) datetimes for the time words in q, or None."""
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if "yesterday" in q or "ayer" in q:
        start, end = day - datetime.timedelta(days=1), day
    elif "last week" in q or "semana pasada" in q:
        start, end = day - datetime.timedelta(days=day.weekday() + 7), day - datetime.timedelta(days=day.weekday())
    elif "this week" in q or "esta semana" in q:
        start, end = day - datetime.timedelta(days=day.weekday()), now
    elif "last month" in q or "mes pasado" in q:
        start, end = day - datetime.timedelta(days=31), day
    elif "today" in q or "hoy" in q:
        start, end = day, now
    else:
        # Weekdays, dates, "hace 3 días", "anoche"...: desktop-memory.py's reading.
        rng = desktop_memory.time_words(q, now)
        return (rng[0], rng[1]) if rng else None
    m = re.search(r"\bat (\d{1,2})(?::(\d{2}))?\s*(am|pm)?", q)
    if m:
        h = int(m[1])
        if m[3] == "pm" and h < 12:
            h += 12
        elif m[3] == "am" and h == 12:
            h = 0
        elif not m[3] and h < 7:
            h += 12                     # "at 3" means the afternoon
        h %= 24
        mid = start.replace(hour=h, minute=int(m[2] or 0))
        start, end = mid - datetime.timedelta(minutes=45), mid + datetime.timedelta(minutes=45)
    return start, end


def fallback_context(question, now, sources=privacy_settings.SOURCES):
    """The searches run here on the question's own words, each only when
    its source is allowed (search_meaning on the whole question, when
    "index" is in sources); ctx["files"] is always there (empty when files
    are off) since the callers read the paths from it."""
    q = question.lower()
    rng = time_range(q, now)
    start, end = rng if rng else (now - datetime.timedelta(days=1), now)
    words = [w for w in re.findall(r"[a-záéíóúñ0-9]+", q) if w not in STOP and len(w) > 2]
    ext = next((e for e in ("pdf", "docx", "xlsx", "pptx", "png", "jpg", "mp4", "zip", "txt") if e in q), None)
    ctx = {}
    if "index" in sources:
        ctx["meaning"] = withhold(search_meaning(question, 6))
    if "memory" in sources:
        ctx["memory"] = search_memory(question)
    if "activity" in sources:
        ctx["activity"] = search_activity(start.isoformat(), end.isoformat())
    file_range = rng or (now - datetime.timedelta(days=60), now)
    ctx["files"] = (withhold(search_files(" ".join(words[:3]) or None, file_range[0].isoformat(),
                                          file_range[1].isoformat(), ext, may_read=content_allowed))
                    if "files" in sources else dict(OFF_NOTE))
    if words and "clipboard" in sources:
        ctx["clipboard"] = search_clipboard(" ".join(words[:2]))
    return ctx


def context_paths(ctx):
    """The file paths in a fallback_context(), the search_meaning ones first
    (then the memory's links and thumbnails)."""
    paths = []
    for key in ("meaning", "memory", "files"):
        part = ctx.get(key)
        if isinstance(part, dict):
            paths += [f["path"] for f in part.get("files", [])]
    return list(dict.fromkeys(paths))


# -- the model -----------------------------------------------------------------
def pick_model():
    local = [m for m in llm_models.local_models()]
    wanted = None
    for key in ("quick", "default"):
        m = llm_models.resolve(llm_models.settings()[key], local, prefix=False)
        if m and m.local:
            wanted = m
            break
    wanted = wanted or (local[0] if local else None)
    # Answers must stay on this machine, so there is no falling back to a
    # Claude model like the launcher's ?? does. Instead: when the wanted model
    # would not fit next to what is on the card (it would spill into RAM and
    # crawl), use a chat model that is already loaded -- it answers at full
    # speed and nothing has to load or unload.
    try:
        gpu = llm_models._gpu_module()
        verdict = gpu.fit_now(wanted) if wanted else None
        if verdict and verdict["verdict"] == "won't fit":
            for row in gpu.lms_ps():
                if row.get("type", "llm") != "llm":      # the index's embedding model
                    continue
                m = llm_models.resolve(row.get("modelKey", ""), local, prefix=False)
                if m and m.local:
                    return m
    except Exception:       # a broken calculator must not cost the answer
        pass
    return wanted


def chat(model, messages, tools=True, offered=None):
    # reasoning_effort "none": a thinking model (GLM) otherwise reasons for
    # minutes and runs out of tokens before any tool call; "/nothink" in the
    # prompt was not reliable, this is (2 s, straight to the tool).
    body = {"model": model.ident, "messages": messages, "temperature": 0.2, "max_tokens": 4000,
            "reasoning_effort": "none"}
    if tools:
        body["tools"] = TOOLS if offered is None else offered
    req = urllib.request.Request(f"http://localhost:{llm_models.server_port()}/v1/chat/completions",
                                 data=json.dumps(body).encode(), headers={"content-type": "application/json"})
    started = time.time()
    with urllib.request.urlopen(req, timeout=CALL_TIMEOUT) as resp:
        msg = json.loads(resp.read())["choices"][0]["message"]
    if os.environ.get("ASK_DEBUG"):
        print(f"ask-desktop: {time.time() - started:.0f} s, content {len(msg.get('content') or '')}, "
              f"reasoning {len(msg.get('reasoning_content') or '')}, "
              f"calls {[c['function']['name'] for c in msg.get('tool_calls') or []]}", file=sys.stderr)
    return msg


def clean(text):
    """Thinking models: drop a <think> block that leaked into the answer."""
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()


def system_prompt(now, sources=privacy_settings.SOURCES):
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    monday = day - datetime.timedelta(days=day.weekday())
    anchors = (f"Yesterday is {day - datetime.timedelta(days=1):%Y-%m-%d}. This week began "
               f"{monday:%Y-%m-%d}; last week ran {monday - datetime.timedelta(days=7):%Y-%m-%d} to "
               f"{monday - datetime.timedelta(days=1):%Y-%m-%d}. ")
    return (f"You answer questions about the user's own computer: their files, clipboard history and "
            f"which windows they had focused. Now is {now:%A %Y-%m-%d %H:%M} (local time). " + anchors +
            "Use the tools to look things up -- never guess paths or activity. Turn relative times "
            "('yesterday at 3pm', 'last week') into ISO local date-times yourself. Answer briefly and "
            "plainly; give full file paths for files you point to. If nothing matches, say so."
            + (" To find what a document says or which file is about a topic, use search_meaning; "
               "search_files only matches names and dates." if "index" in sources else "")
            + (" For what they saw, copied, were sent or heard (links, errors, messages), use "
               "search_memory, and give the link or time it returns." if "memory" in sources else "")
            + off_sentence(sources))


def off_sentence(sources):
    off = [s for s in privacy_settings.SOURCES if s not in sources]
    if not off:
        return ""
    names = {"files": "their files", "clipboard": "their clipboard history", "activity": "their window history"}
    return (" The user has not allowed you to read " + " or ".join(names[s] for s in off)
            + "; if the question needs that, say it is turned off in Settings > Privacy.")


def ask(question):
    now = datetime.datetime.now()
    conf = privacy_settings.load()
    if not privacy_settings.ask_on(conf):
        return OFF_ANSWER, []
    sources = privacy_settings.ask_sources(conf)
    if not sources:
        return NO_SOURCES, []
    if "files" in sources and index_ready(conf):
        sources.add("index")
    if memory_ready(conf):
        sources.add("memory")
    offered = allowed_tools(sources)
    model = pick_model()
    if model is None:
        return "No local model in LM Studio (lms ls shows none).", []
    ok, why = llm_models.ensure_local(model)
    if not ok:
        return f"Could not start the local model: {why}", []
    messages = [{"role": "system", "content": system_prompt(now, sources)}, {"role": "user", "content": question}]
    seen_files = []
    try:
        used_tools = False
        for _ in range(MAX_ROUNDS):
            msg = chat(model, messages, offered=offered)
            calls = msg.get("tool_calls") or []
            if not calls:
                break
            used_tools = True
            messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
            for call in calls:
                fn = call.get("function", {})
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                    result = call_search(fn["name"], {k: v for k, v in args.items() if v not in (None, "")},
                                         sources)
                except (KeyError, TypeError, ValueError) as exc:
                    result = {"error": str(exc)}
                seen_files += [f["path"] for f in result.get("files", [])] if isinstance(result, dict) else []
                if os.environ.get("ASK_DEBUG"):
                    print(f"ask-desktop: {fn.get('name')}({fn.get('arguments')}) -> "
                          f"{result.get('count', len(result.get('entries', result.get('windows', []))))}"
                          if isinstance(result, dict) else "", file=sys.stderr)
                messages.append({"role": "tool", "tool_call_id": call.get("id", ""),
                                 "content": json.dumps(result, ensure_ascii=False)[:12000]})
        else:
            msg = chat(model, messages, tools=False)
        answer = clean(msg.get("content"))
        if not used_tools:
            # No tool calls: look things up here and let the model read them.
            ctx = fallback_context(question, now, sources)
            seen_files = context_paths(ctx)
            messages = [{"role": "system", "content": system_prompt(now, sources) + " The lookups are already done; "
                         "answer from the results below only."},
                        {"role": "user", "content": question + "\n\nResults:\n"
                         + json.dumps(ctx, ensure_ascii=False)[:14000]}]
            answer = clean(chat(model, messages, tools=False).get("content"))
    except urllib.error.HTTPError as exc:
        if exc.code == 400 and not seen_files:
            # A server / model that rejects the tools parameter outright.
            ctx = fallback_context(question, now, sources)
            seen_files = context_paths(ctx)
            messages = [{"role": "system", "content": system_prompt(now, sources)},
                        {"role": "user", "content": question + "\n\nResults:\n"
                         + json.dumps(ctx, ensure_ascii=False)[:14000]}]
            answer = clean(chat(model, messages, tools=False).get("content"))
        else:
            return f"The local model failed: HTTP {exc.code}", []
    except (urllib.error.URLError, OSError, ValueError, KeyError) as exc:
        return f"The local model failed: {exc}", []
    mentioned = [p for p in dict.fromkeys(seen_files) if p in answer or os.path.basename(p) in answer]
    return answer or "(no answer)", mentioned or list(dict.fromkeys(seen_files))[:5]


NOTIFY_TAG = ["-a", "Ask your desktop", "-h", "string:x-canonical-private-synchronous:ask-desktop"]


def notify_answer(question):
    subprocess.run(["notify-send", *NOTIFY_TAG, "-u", "low", "-t", "0", "Asking your desktop…", question])
    answer, files = ask(question)
    # Files, and the desktop memory's links (search_memory) by their site.
    files = [f for f in files if os.path.exists(f) or f.startswith(("http://", "https://"))][:3]
    actions = [f"--action=open{i}=Open " + (re.sub(r"^https?://(www\.)?", "", f).split("/")[0] if "://" in f
                                             else os.path.basename(f))[:40] for i, f in enumerate(files)]
    try:
        out = subprocess.run(["notify-send", *NOTIFY_TAG, "-t", "60000", "-i", "system-search",
                              *actions, *(["--wait"] if actions else []), question, answer[:1500]],
                             capture_output=True, text=True, timeout=120).stdout.strip()
    except subprocess.TimeoutExpired:
        return
    if out.startswith("open") and out[4:].isdigit() and int(out[4:]) < len(files):
        subprocess.Popen(["gio", "open", files[int(out[4:])]], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main(argv):
    as_json = "--json" in argv
    question = " ".join(a for a in argv if a not in ("--json", "--notify")).strip()
    if not question:
        sys.exit(__doc__)
    if "--notify" in argv:
        notify_answer(question)
        return
    answer, files = ask(question)
    if as_json:
        print(json.dumps({"answer": answer, "files": files}, ensure_ascii=False))
    else:
        print(answer)


if __name__ == "__main__":
    main(sys.argv[1:])
