#!/usr/bin/env python3
"""The search index behind "Ask your desktop": the text of your documents,
cut into pieces and kept so they can be found by what they are ABOUT, not
only by their names. Everything stays on this computer.

    desktop-index.py build [--only DIR] [--max-minutes N]
                                   index what is new or changed (the first
                                   time: everything); same as update but
                                   without the game-mode / battery checks
    desktop-index.py update [--max-minutes N]
                                   what the hourly timer runs: the same,
                                   skipped while game mode is on, a Steam
                                   game is open, or on battery; then the
                                   desktop memory's new embeddings
                                   (desktop-memory.py embed_hourly)
    desktop-index.py status [--json]
                                   files, pieces, last update, size on disk,
                                   the embedding model (or "keyword only")
    desktop-index.py search QUERY [-k N] [--json]
                                   the best-matching pieces, with their file
    desktop-index.py plan          what a build would read (files, bytes),
                                   nothing written
    desktop-index.py clear         delete the index (the files themselves
                                   are not touched)

What is indexed -- these folders and nothing else:

    ~/Documents, ~/Downloads, ~/Desktop   every folder inside them
    your projects folder                  each git repo's own files
    (desktop_conf.py; only when it is
    inside your home folder)
                                          (`git ls-files`, so .gitignore is
                                          respected); plain folders walked

Only .txt .md .py .js .html .htm .json .csv and PDFs (pdftotext, when
installed); files over 2 MB, binaries (a NUL byte), minified code (very long
lines) and lock files are left out. Never, whatever folder they are in:
hidden files and folders (so ~/.ssh, ~/.gnupg, ~/.password-store,
~/.local/share/keyrings and the browser profiles are never even visited --
NEVER below lists them too, in case a link points there), node_modules,
files named like *secret*, *credentials*, *password*, *.env, id_rsa* /
id_ed25519*, *.pem / *.key, and any file with a PRIVATE KEY block in it.
The clipboard is not indexed.

Privacy (privacy.conf, privacy_settings.py): with ask, ask_files or
ask_index off, build / update do nothing and search answers "turned off".
`clear` works whatever the switches say.

How: each file's text is cut into ~800-character pieces that overlap by 150,
and each piece gets
  * an embedding (a list of numbers for its meaning) from a small local
    model through LM Studio's /v1/embeddings -- nomic-embed-text-v1.5
    (~80 MB) when installed, any embedding model otherwise; kept as the
    first 256 numbers (nomic is trained so that a shortened one still
    works), float32 blobs. LM Studio's server is started if it has to be,
    the model loaded with a short TTL so it unloads itself; no chat model
    is ever loaded or unloaded here. No embedding model: `lms get
    https://huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF -y`
  * its words, for a plain BM25 keyword index (pure Python), so search
    still works with no model, or before the embeddings are done.
search() mixes the two (reciprocal rank fusion) when both are there.

Store: $XDG_CACHE_HOME/desktop-index/index.sqlite3. Incremental: a file is
read again only when its size or mtime changed; files that are gone (or are
now excluded) are dropped. Resumable: the words go in a file at a time and
the embeddings a batch at a time, each committed, so a build that is
stopped picks up where it was. One build at a time (a lock file).
Runs itself at nice 19 / idle I/O; desktop-index.timer (hourly) runs
`update --auto` through desktop-index.service (Nice=19, IOSchedulingClass=
idle, CPUQuota=200%).
"""
import array
import fcntl
import html
import importlib.util
import json
import math
import os
import re
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import desktop_conf  # noqa: E402
import privacy_settings  # noqa: E402

try:
    import numpy  # noqa: F401  (faster cosine when it is there; plain Python otherwise)
except ImportError:
    numpy = None

HOME = os.path.expanduser("~")
CACHE_HOME = os.environ.get("XDG_CACHE_HOME") or os.path.join(HOME, ".cache")
DIR = os.path.join(CACHE_HOME, "desktop-index")
DB = os.path.join(DIR, "index.sqlite3")
LOCK = os.path.join(DIR, "lock")
LMS = os.path.join(HOME, ".lmstudio", "bin", "lms")

PLAIN_ROOTS = ["Documents", "Downloads", "Desktop"]
# Your projects folder (desktop.conf), relative to home -- the tests and
# candidates() join it to the home they are given. One outside home is left
# out like everything else outside it (excluded()).
REPO_ROOT = os.path.relpath(desktop_conf.projects_dir(), HOME)
EXTENSIONS = {".txt", ".md", ".markdown", ".py", ".js", ".html", ".htm", ".json", ".csv", ".pdf"}
MAX_BYTES = 2 * 1024 * 1024
SKIP_DIRS = {"node_modules", "bower_components", "__pycache__", "site-packages", "venv"}
# Never read, even through a symlink. All hidden, so the walk never enters
# them anyway; this is the second lock on the door.
NEVER = [os.path.join(HOME, p) for p in (
    ".ssh", ".gnupg", ".password-store", ".local/share/keyrings", ".local/share/kwalletd",
    ".mozilla", ".librewolf", ".thunderbird", ".config/google-chrome", ".config/chromium",
    ".config/BraveSoftware", ".config/vivaldi", ".config/microsoft-edge", ".var/app",
    ".config/keepassxc", ".pki", ".aws", ".kube", ".docker")]
SECRET_NAME = re.compile(r"secret|credential|password|passwd|^id_(rsa|dsa|ecdsa|ed25519)|\.env$|^\.env|"
                         r"\.(pem|key|p12|pfx|kdbx|gpg|asc)$", re.I)
LOCK_FILES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "composer.lock", "poetry.lock"}
PRIVATE_KEY = "PRIVATE KEY-----"
MINIFIED_LINE = 2000        # a line longer than this: minified / generated, left out

CHUNK = 800
OVERLAP = 150
MAX_CHUNKS_PER_FILE = 150   # ~120 KB of text; past that, a file is mostly data
EMBED_BATCH = 32            # pieces per /v1/embeddings call
DIM = 256                   # numbers kept per embedding
EMBED_TTL = 600             # s idle before LM Studio unloads the embedding model
PREFERRED_EMBED = "nomic-embed-text"
PDF_PAGES = 60
K1, B = 1.2, 0.75           # BM25
RRF = 60                    # reciprocal rank fusion's constant
STOP = set("the a an and or of to in on at for from by with is are was were be been it its this that "
           "these those as not no but if then so than into out up do does did have has had i you he she "
           "we they my your our their me him her us them what which who when where how why can will "
           "would should could all any some more most other such only own same too very just also "
           "el la los las un una y o de del en que por con para es se no al lo como".split())

OFF_TEXT = "The search index is turned off (Settings > Privacy)."


# -- privacy ---------------------------------------------------------------------
def allowed(conf=None):
    """True when the switches let the index be built and searched: ask,
    ask_files and ask_index all on."""
    conf = privacy_settings.load() if conf is None else conf
    return (privacy_settings.ask_on(conf) and privacy_settings.flag(conf.get("ask_files", "on"))
            and privacy_settings.flag(conf.get("ask_index", "on")))


# -- which files ---------------------------------------------------------------------
def roots(home=HOME):
    """The folders indexed, as the user is told them."""
    return [os.path.join(home, r) for r in PLAIN_ROOTS] + [os.path.join(home, REPO_ROOT)]


def under(path, folder):
    return path == folder or path.startswith(folder.rstrip(os.sep) + os.sep)


def excluded(path, home=HOME):
    """Why `path` (absolute) is never indexed, or None. By name only; the
    content checks are in read_text()."""
    real = os.path.realpath(path)
    for p in (path, real):
        if any(under(p, n.replace(HOME, home, 1)) for n in NEVER):
            return "private folder"
    rel = os.path.relpath(path, home)
    if rel.startswith(".."):
        return "outside the home folder"
    parts = rel.split(os.sep)
    if any(part.startswith(".") for part in parts):
        return "hidden"
    if any(part in SKIP_DIRS for part in parts[:-1]):
        return "dependencies"
    name = parts[-1]
    if SECRET_NAME.search(name):
        return "looks secret"
    low = name.lower()
    if low in LOCK_FILES or low.endswith((".min.js", ".min.css", ".map")):
        return "generated"
    if os.path.splitext(low)[1] not in EXTENSIONS:
        return "not text"
    return None


def walk(top):
    for root, dirs, files in os.walk(top):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS)
        for f in sorted(files):
            if not f.startswith("."):
                yield os.path.join(root, f)


def repo_files(repo):
    """A git repo's own files: tracked, plus untracked ones .gitignore lets
    through."""
    try:
        out = subprocess.run(["git", "-C", repo, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                             capture_output=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [os.path.join(repo, p) for p in sorted(set(out.decode(errors="replace").split("\0"))) if p]


def candidates(home=HOME, only=None):
    """{path: (mtime_ns, size)} of every file the index should hold."""
    paths = []
    for r in PLAIN_ROOTS:
        top = os.path.join(home, r)
        if os.path.isdir(top) and (only is None or under(top, only) or under(only, top)):
            paths += [p for p in walk(top) if only is None or under(p, only)]
    gh = os.path.join(home, REPO_ROOT)
    if os.path.isdir(gh) and (only is None or under(gh, only) or under(only, gh)):
        for entry in sorted(os.scandir(gh), key=lambda e: e.name):
            if entry.name.startswith(".") or not entry.is_dir(follow_symlinks=False):
                continue
            found = (repo_files(entry.path) if os.path.exists(os.path.join(entry.path, ".git"))
                     else list(walk(entry.path)))
            paths += [p for p in found if only is None or under(p, only)]
    out = {}
    for p in paths:
        if excluded(p, home):
            continue
        try:
            st = os.stat(p)
        except OSError:
            continue
        if not os.path.isfile(p) or st.st_size == 0 or st.st_size > MAX_BYTES:
            continue
        out[p] = (st.st_mtime_ns, st.st_size)
    return out


# -- reading the text ----------------------------------------------------------------
def html_text(raw):
    raw = re.sub(r"(?is)<(script|style|noscript|svg)\b.*?</\1>", " ", raw)
    raw = re.sub(r"(?s)<!--.*?-->", " ", raw)
    raw = re.sub(r"<[^>]+>", " ", raw)
    return html.unescape(raw)


def read_text(path):
    """(text, None) or (None, why it is left out)."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        try:
            res = subprocess.run(["pdftotext", "-q", "-l", str(PDF_PAGES), "-enc", "UTF-8", path, "-"],
                                 capture_output=True, timeout=60)
        except FileNotFoundError:
            return None, "no pdftotext"
        except (OSError, subprocess.SubprocessError):
            return None, "pdftotext failed"
        text = res.stdout.decode(errors="replace")
    else:
        try:
            with open(path, "rb") as handle:
                data = handle.read(MAX_BYTES + 1)
        except OSError:
            return None, "unreadable"
        if b"\0" in data[:8192]:
            return None, "binary"
        text = data.decode("utf-8", errors="replace")
        if ext in (".js", ".json", ".html", ".htm", ".csv") and \
                max((len(line) for line in text.splitlines()), default=0) > MINIFIED_LINE:
            return None, "minified"
        if ext in (".html", ".htm"):
            text = html_text(text)
    if PRIVATE_KEY in text:
        return None, "has a private key"
    if len(text.split()) < 5:
        return None, "no text"
    return text, None


def chunks(text, size=CHUNK, overlap=OVERLAP):
    """The text with its whitespace squeezed, cut into pieces of at most
    `size` characters that overlap by about `overlap`, each cut at a space
    where there is one in the last 40 % of the piece."""
    text = " ".join(text.split())
    if not text:
        return []
    out, start, n = [], 0, len(text)
    while start < n:
        end = min(start + size, n)
        if end < n:
            cut = text.rfind(" ", start + int(size * 0.6), end)
            if cut > start:
                end = cut
        piece = text[start:end].strip()
        if piece:
            out.append(piece)
        if end >= n:
            break
        nxt = max(end - overlap, start + 1)
        space = text.find(" ", nxt, end)
        start = space + 1 if space != -1 else nxt
    return out


def tokens(text):
    return [w for w in re.findall(r"[^\W_]+", text.lower()) if 1 < len(w) <= 40 and w not in STOP]


# -- the database ---------------------------------------------------------------------
SCHEMA = """
create table if not exists meta(key text primary key, value text);
create table if not exists files(path text primary key, mtime integer, size integer, chunks integer,
                                 skipped text, indexed real);
create table if not exists chunks(id integer primary key, path text, seq integer, text text,
                                  ntok integer, vec blob);
create index if not exists chunks_path on chunks(path);
create table if not exists postings(term text, chunk integer, tf integer, primary key(term, chunk))
    without rowid;
"""


def connect(path=None):
    path = path or DB
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    con = sqlite3.connect(path, timeout=30)
    con.executescript(SCHEMA)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return con


def meta(con, key, value=None):
    if value is None:
        row = con.execute("select value from meta where key=?", (key,)).fetchone()
        return row[0] if row else None
    con.execute("insert or replace into meta values(?, ?)", (key, str(value)))


def drop_file(con, path):
    for cid, text in con.execute("select id, text from chunks where path=?", (path,)).fetchall():
        con.executemany("delete from postings where term=? and chunk=?", [(t, cid) for t in set(tokens(text))])
    con.execute("delete from chunks where path=?", (path,))
    con.execute("delete from files where path=?", (path,))


def add_file(con, path, mtime, size, pieces, skipped=None):
    drop_file(con, path)
    for seq, piece in enumerate(pieces):
        toks = tokens(piece)
        cur = con.execute("insert into chunks(path, seq, text, ntok) values(?, ?, ?, ?)",
                          (path, seq, piece, len(toks)))
        tf = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        con.executemany("insert into postings values(?, ?, ?)", [(t, cur.lastrowid, n) for t, n in tf.items()])
    con.execute("insert into files values(?, ?, ?, ?, ?, ?)", (path, mtime, size, len(pieces), skipped, time.time()))


def changes(con, current):
    """(paths to (re)read, paths to drop): what differs between the files
    table and `current` {path: (mtime_ns, size)}."""
    known = {p: (m, s) for p, m, s in con.execute("select path, mtime, size from files")}
    todo = [p for p, st in current.items() if known.get(p) != st]
    gone = [p for p in known if p not in current]
    return sorted(todo), sorted(gone)


# -- LM Studio's embeddings ---------------------------------------------------------
def port():
    try:
        with open(os.path.join(HOME, ".lmstudio", ".internal", "http-server-config.json")) as h:
            return int(json.load(h).get("port") or 1234)
    except (OSError, ValueError, TypeError):
        return 1234


def _get(url, timeout=5):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read())


def server_models():
    """LM Studio's own model list (id, type, state), [] when it is not up.
    Read over HTTP: no node CLI start for this."""
    try:
        return _get(f"http://localhost:{port()}/api/v0/models").get("data") or []
    except (urllib.error.URLError, OSError, ValueError):
        return None


def pick_embedding(models):
    emb = [m for m in models or [] if m.get("type") == "embeddings"]
    emb.sort(key=lambda m: (PREFERRED_EMBED not in m.get("id", ""), m.get("state") != "loaded", m.get("id", "")))
    return emb[0] if emb else None


def start_daemon(log=lambda text: None):
    """LM Studio's daemon started inside its limits (lmstudio.service, via
    llm-limits.py's ensure_daemon, as llm_models.ensure_local does) before
    `lms server start` -- which would otherwise start it outside them, where
    the idle reaper (llm-limits.py reap) cannot stop it again."""
    try:
        import llm_models
        note = llm_models._limits_module().ensure_daemon()
    except Exception as exc:       # noqa: BLE001 -- no limits script: lms starts it the old way
        note = str(exc)
    if note:
        log(note)


def embedding_model(start=False, log=lambda text: None):
    """The embedding model's id, loaded and ready, or None. With start=True
    LM Studio's server is started if it is not up. Never touches a chat
    model: only `lms load <embedding model>` with a short TTL."""
    models = server_models()
    if models is None and start and os.access(LMS, os.X_OK):
        log("starting LM Studio's server")
        start_daemon(log)
        try:
            subprocess.run([LMS, "server", "start"], capture_output=True, timeout=90)
        except (OSError, subprocess.SubprocessError):
            return None
        models = server_models()
    m = pick_embedding(models)
    if m is None:
        return None
    if m.get("state") != "loaded":
        log(f"loading {m['id']}")
        try:
            subprocess.run([LMS, "load", m["id"], "-y", "--ttl", str(EMBED_TTL)], capture_output=True, timeout=120)
        except (OSError, subprocess.SubprocessError):
            return None
        if (pick_embedding(server_models()) or {}).get("state") != "loaded":
            return None
    return m["id"]


def embed(model, texts, timeout=120):
    """[array('f')] of DIM numbers each, unit length."""
    body = json.dumps({"model": model, "input": texts}).encode()
    req = urllib.request.Request(f"http://localhost:{port()}/v1/embeddings", data=body,
                                 headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())["data"]
    out = []
    for row in sorted(data, key=lambda r: r.get("index", 0)):
        v = row["embedding"][:DIM]
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        out.append(array.array("f", [x / norm for x in v]))
    return out


def doc_text(path, piece):
    return f"search_document: {os.path.relpath(path, HOME)}\n{piece}"


# -- building --------------------------------------------------------------------------
def be_gentle():
    """Nice 19 and idle I/O for this process (the timer's unit says so too)."""
    try:
        os.nice(19 - os.nice(0))
    except OSError:
        pass
    try:
        subprocess.run(["ionice", "-c", "3", "-p", str(os.getpid())], capture_output=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        pass


def busy():
    """Why the timer's run should wait (game mode, a Steam game, battery),
    or None. Game mode is lua/gamemode.lua's: animations off."""
    try:
        if subprocess.run(["systemd-ac-power"], timeout=5).returncode != 0:
            return "on battery"
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        opt = json.loads(subprocess.run(["hyprctl", "-j", "getoption", "animations:enabled"],
                                        capture_output=True, text=True, timeout=3).stdout or "{}")
        if opt.get("int", opt.get("bool", 1)) in (0, False):
            return "game mode is on"
        clients = json.loads(subprocess.run(["hyprctl", "-j", "clients"], capture_output=True, text=True,
                                            timeout=3).stdout or "[]")
        if any((c.get("class") or "").startswith("steam_app_") for c in clients):
            return "a game is running"
    except (OSError, subprocess.SubprocessError, ValueError, AttributeError):
        pass
    return None


def take_lock():
    os.makedirs(DIR, mode=0o700, exist_ok=True)
    handle = open(LOCK, "w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def running():
    if not os.path.exists(LOCK):
        return False
    handle = take_lock()
    if handle is None:
        return True
    handle.close()
    return False


def build(only=None, max_minutes=None, check_busy=False, log=print, home=HOME, con=None, model=None):
    """Bring the index up to date. Returns a short summary line."""
    if not allowed():
        return OFF_TEXT
    lock = take_lock() if con is None else True
    if lock is None:
        return "an index build is already running"
    started = time.time()
    deadline = started + max_minutes * 60 if max_minutes else None
    own = con is None
    con = con or connect()
    last_check = [0.0]

    def stop():
        if deadline and time.time() > deadline:
            return "time is up"
        if check_busy and time.time() - last_check[0] > 30:
            last_check[0] = time.time()
            return busy()
        return None

    try:
        current = candidates(home, only)
        todo, gone = changes(con, current)
        if only is not None:
            gone = [p for p in gone if under(p, only)]
        for p in gone:
            drop_file(con, p)
        con.commit()
        log(f"{len(current)} files in scope, {len(todo)} new or changed, {len(gone)} gone")
        done, why = 0, None
        for i, p in enumerate(todo):
            if i % 25 == 0:
                why = stop()
                if why:
                    break
                meta(con, "progress", f"reading {i} / {len(todo)}")
            text, skipped = read_text(p)
            pieces = chunks(text)[:MAX_CHUNKS_PER_FILE] if text else []
            add_file(con, p, *current[p], pieces, skipped)
            done += 1
            if i % 25 == 24:
                con.commit()
        con.commit()
        embedded = 0
        if not why:
            embedded, why = embed_pending(con, stop, log, model)
        meta(con, "progress", "")
        if not why:
            meta(con, "updated", time.time())
        con.commit()
        took = time.time() - started
        line = f"read {done} files, embedded {embedded} pieces in {took:.0f} s"
        return line + (f"; stopped: {why} (the next run carries on)" if why else "")
    finally:
        if own:
            con.close()
            lock.close()


def embed_pending(con, stop, log, model=None):
    """Embeddings for the pieces that have none, a batch per commit.
    (count, why it stopped or None)."""
    pending = con.execute("select count(*) from chunks where vec is null").fetchone()[0]
    if not pending:
        # Nothing new; only a different embedding model (asked over HTTP,
        # nothing started or loaded for this) means work.
        now = model or (pick_embedding(server_models()) or {}).get("id")
        if not now or meta(con, "model") in (None, now):
            return 0, None
    model = model or embedding_model(start=True, log=log)
    if model is None:
        log("no embedding model in LM Studio: keyword search only for now")
        return 0, None
    if meta(con, "model") not in (None, model):
        log(f"embedding model changed to {model}: embedding everything again")
        con.execute("update chunks set vec=null")
        pending = con.execute("select count(*) from chunks").fetchone()[0]
    meta(con, "model", model)
    meta(con, "dim", DIM)
    con.commit()
    count = 0
    while True:
        why = stop()
        if why:
            return count, why
        rows = con.execute("select id, path, text from chunks where vec is null limit ?",
                           (EMBED_BATCH,)).fetchall()
        if not rows:
            return count, None
        try:
            vecs = embed(model, [doc_text(p, t) for _, p, t in rows])
        except (urllib.error.URLError, OSError, ValueError, KeyError) as exc:
            return count, f"LM Studio failed: {exc}"
        con.executemany("update chunks set vec=? where id=?", [(v.tobytes(), r[0]) for v, r in zip(vecs, rows)])
        count += len(rows)
        meta(con, "progress", f"embedding {count} / {pending}")
        con.commit()


def embed_memories(log=lambda text: None):
    """The desktop memory's embeddings, in the same hourly run (moved here
    from desktop-memory.py collect, which ran every 5 minutes and kept LM
    Studio awake). desktop-memory.py decides when LM Studio may be started
    for them (embed_hourly). The line to print."""
    try:
        spec = importlib.util.spec_from_file_location(
            "desktop_memory", os.path.join(os.path.dirname(os.path.abspath(__file__)), "desktop-memory.py"))
        dm = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(dm)
        n = dm.embed_hourly(log)
    except Exception as exc:       # noqa: BLE001 -- the index's run is done; the memories wait
        return f"desktop memory: not embedded ({exc})"
    return f"desktop memory: {n} embedded"


# -- searching ----------------------------------------------------------------------------
def bm25(con, query, limit=50):
    """[(chunk id, score)] best first, plain BM25 over the postings."""
    terms = list(dict.fromkeys(tokens(query)))
    if not terms:
        return []
    n, total = con.execute("select count(*), coalesce(sum(ntok), 0) from chunks").fetchone()
    if not n:
        return []
    avg = total / n or 1.0
    lengths = {}
    scores = {}
    for t in terms:
        rows = con.execute("select chunk, tf from postings where term=?", (t,)).fetchall()
        if not rows:
            continue
        idf = math.log(1 + (n - len(rows) + 0.5) / (len(rows) + 0.5))
        need = [c for c, _ in rows if c not in lengths]
        for i in range(0, len(need), 900):
            part = need[i:i + 900]
            lengths.update(con.execute(f"select id, ntok from chunks where id in ({','.join('?' * len(part))})",
                                       part).fetchall())
        for c, tf in rows:
            dl = lengths.get(c, avg)
            scores[c] = scores.get(c, 0.0) + idf * tf * (K1 + 1) / (tf + K1 * (1 - B + B * dl / avg))
    return sorted(scores.items(), key=lambda kv: -kv[1])[:limit]


def cosine_top(con, qvec, limit=50):
    rows = con.execute("select id, vec from chunks where vec is not null").fetchall()
    if not rows:
        return []
    if numpy is not None:
        mat = numpy.frombuffer(b"".join(v for _, v in rows), dtype=numpy.float32).reshape(len(rows), -1)
        sims = mat @ numpy.asarray(qvec, dtype=numpy.float32)
        top = numpy.argsort(-sims)[:limit]
        return [(rows[i][0], float(sims[i])) for i in top]
    scored = []
    for cid, blob in rows:
        v = array.array("f")
        v.frombytes(blob)
        scored.append((cid, sum(a * b for a, b in zip(v, qvec))))
    scored.sort(key=lambda kv: -kv[1])
    return scored[:limit]


def search(query, k=8, con=None, model=None, use_model=True):
    """{"results": [{path, snippet, score, modified}], "mode": ...} or
    {"note": ...}. At most two pieces per file."""
    if not allowed():
        return {"note": OFF_TEXT, "off": True}
    own = con is None
    if own:
        if not os.path.exists(DB):
            return {"note": "there is no search index yet (desktop-index.py build)"}
        con = connect()
    try:
        ranked_kw = bm25(con, query)
        ranked_sem = []
        has_vec = con.execute("select 1 from chunks where vec is not null limit 1").fetchone()
        if has_vec and use_model:
            model = model or embedding_model(start=False)
            if model:
                try:
                    ranked_sem = cosine_top(con, embed(model, [f"search_query: {query}"], timeout=30)[0])
                except (urllib.error.URLError, OSError, ValueError, KeyError):
                    ranked_sem = []
        fused = {}
        for ranked in (ranked_sem, ranked_kw):
            for rank, (cid, _) in enumerate(ranked):
                fused[cid] = fused.get(cid, 0.0) + 1.0 / (RRF + rank)
        order = sorted(fused.items(), key=lambda kv: -kv[1])
        results, per_file = [], {}
        for cid, score in order:
            row = con.execute("select path, text from chunks where id=?", (cid,)).fetchone()
            if not row or per_file.get(row[0], 0) >= 2:
                continue
            try:
                mtime = os.stat(row[0]).st_mtime
            except OSError:
                continue            # gone since the last update
            per_file[row[0]] = per_file.get(row[0], 0) + 1
            results.append({"path": row[0], "snippet": row[1][:400], "score": round(score, 4),
                            "modified": time.strftime("%Y-%m-%dT%H:%M", time.localtime(mtime))})
            if len(results) >= k:
                break
        mode = "meaning + keywords" if ranked_sem else "keywords only"
        return {"mode": mode, "results": results}
    finally:
        if own:
            con.close()


# -- status / clear ---------------------------------------------------------------------
def disk_size():
    total = 0
    for name in os.listdir(DIR) if os.path.isdir(DIR) else []:
        try:
            total += os.path.getsize(os.path.join(DIR, name))
        except OSError:
            pass
    return total


def status():
    out = {"on": allowed(), "exists": os.path.exists(DB), "roots": [r.replace(HOME, "~", 1) for r in roots()],
           "path": DB, "running": running(), "bytes": disk_size(), "files": 0, "skipped": 0, "chunks": 0,
           "embedded": 0, "model": None, "updated": None, "progress": ""}
    if out["exists"]:
        con = sqlite3.connect(DB, timeout=10)
        try:
            out["files"], out["skipped"] = con.execute(
                "select count(*), coalesce(sum(chunks = 0), 0) from files").fetchone()
            out["files"] -= out["skipped"]
            out["chunks"], out["embedded"] = con.execute(
                "select count(*), count(vec) from chunks").fetchone()
            rows = dict(con.execute("select key, value from meta").fetchall())
            out["model"] = rows.get("model") if out["embedded"] else None
            out["updated"] = float(rows["updated"]) if rows.get("updated") else None
            out["progress"] = rows.get("progress") or ""
        except sqlite3.Error:
            pass
        finally:
            con.close()
    return out


def human_status(s):
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(s["updated"])) if s["updated"] else "never"
    lines = [f"search index   {'on' if s['on'] else 'off (Settings > Privacy)'}"
             + ("  ·  building now" + (f": {s['progress']}" if s["progress"] else "") if s["running"] else ""),
             f"folders        {', '.join(s['roots'])}",
             f"files          {s['files']} indexed ({s['skipped']} looked at and left out)",
             f"pieces         {s['chunks']}, {s['embedded']} with an embedding",
             f"model          {s['model'] or 'keyword only'}",
             f"last update    {when}",
             f"size on disk   {s['bytes'] / 1024 / 1024:.1f} MiB  ({s['path']})"]
    return "\n".join(lines)


def clear():
    if running():
        sys.exit("desktop-index: a build is running; stop it first (systemctl --user stop desktop-index)")
    for name in ("index.sqlite3", "index.sqlite3-journal", "index.sqlite3-wal", "index.sqlite3-shm", "lock"):
        try:
            os.unlink(os.path.join(DIR, name))
        except FileNotFoundError:
            pass
    try:
        os.rmdir(DIR)
    except OSError:
        pass


def plan(only=None):
    current = candidates(HOME, only)
    per = {}
    for p, (_, size) in current.items():
        top = os.path.relpath(p, HOME).split(os.sep)[0]
        n, b = per.get(top, (0, 0))
        per[top] = (n + 1, b + size)
    return {"files": len(current), "bytes": sum(s for _, s in current.values()),
            "per_folder": {k: {"files": n, "bytes": b} for k, (n, b) in sorted(per.items())}}


# -- the command line ---------------------------------------------------------------------
def option(args, name, cast=str, default=None):
    if name in args:
        i = args.index(name)
        if i + 1 < len(args):
            value = args[i + 1]
            del args[i:i + 2]
            return cast(value)
    return default


def main(argv):
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return
    cmd, args = argv[0], list(argv[1:])
    as_json = "--json" in args
    args = [a for a in args if a != "--json"]
    if cmd in ("build", "update"):
        auto = "--auto" in args
        args = [a for a in args if a != "--auto"]
        only = option(args, "--only")
        minutes = option(args, "--max-minutes", float)
        if only:
            only = os.path.abspath(os.path.expanduser(only))
        if cmd == "update":
            why = busy()
            if why:
                print(f"desktop-index: skipped, {why}")
                return
        be_gentle()
        print(build(only, minutes, check_busy=cmd == "update", log=lambda t: print(t, flush=True)))
        if cmd == "update" and not only:
            print(embed_memories(log=lambda t: print(t, flush=True)))
    elif cmd == "status":
        s = status()
        print(json.dumps(s) if as_json else human_status(s))
    elif cmd == "search":
        k = option(args, "-k", int, 8)
        query = " ".join(args).strip()
        if not query:
            sys.exit("desktop-index: search what?")
        res = search(query, k)
        if as_json:
            print(json.dumps(res, ensure_ascii=False))
        elif "note" in res:
            print(res["note"])
        else:
            print(f"({res['mode']})")
            for r in res["results"]:
                print(f"{r['score']:.4f}  {r['path']}\n        {r['snippet'][:200]}")
    elif cmd == "plan":
        print(json.dumps(plan(option(args, "--only")), indent=1))
    elif cmd == "clear":
        clear()
        print("desktop-index: the index is deleted")
    else:
        sys.exit(f"desktop-index: unknown command {cmd!r} (desktop-index.py --help)")


if __name__ == "__main__":
    main(sys.argv[1:])
