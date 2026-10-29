#!/usr/bin/env python3
"""Backups of your files: a daily, encrypted, deduplicated copy of the folders
you choose, kept to a policy -- through restic (preferred) or kopia, whichever
is installed. This script only drives them; the repository is theirs, so it
can be read back with the plain tool on any machine.

    backup.py status [--json]      the engine, the repository, the last run and
                                   its size, the schedule, what is included
    backup.py run [--timer]        back up now, then thin the old snapshots to
                                   the keep policy and read the repository size.
                                   --timer: backup.timer's run -- nothing (exit 0)
                                   when no backup is set up
    backup.py snapshots [--json]   the snapshots in the repository
    backup.py restore-hint         how to get files back (the commands, filled in)
    backup.py init                 make the repository (Settings' "Create" button:
                                   only ever on your click)
    backup.py configured           exit 0 when a backup is set up and its engine
                                   installed (backup.service's ExecCondition)
    backup.py set KEY VALUE        engine (auto|restic|kopia), repo, password
                                   (keyring | file:PATH), keep_daily /
                                   keep_weekly / keep_monthly (numbers)
    backup.py include add|remove PATH    the folders backed up
    backup.py exclude add|remove PATTERN what is left out of them
    backup.py password store       the repository password from stdin into the
                                   Secret Service (GNOME keyring / KeePassXC),
                                   via secret-tool
    backup.py schedule on|off      the daily backup.timer
    backup.py open                 the repository folder in the file manager
                                   (a local repository only)

THE SETTINGS are ~/.config/hypr/backup.conf, key=value, one include= or
exclude= line per entry (HYPR_BACKUP_CONF points elsewhere, for the tests):

    engine=auto                    restic when installed, else kopia
    repo=/run/media/you/Disk/backup   a folder, or restic's sftp:/rest:/s3:/b2:
                                   URLs (kopia: a folder only)
    password=keyring               the Secret Service (secret-tool, attribute
                                   service=hypr-backup repo=<repo>), or
                                   file:~/.config/hypr/backup.pass (mode 0600:
                                   a file anyone else can read is refused)
    include=~/Documents ...        DEFAULT_INCLUDE below
    exclude=~/.cache ...           DEFAULT_EXCLUDE below
    keep_daily=7 keep_weekly=4 keep_monthly=6

The password never goes on a command line or into this file: restic reads it
through RESTIC_PASSWORD_COMMAND (secret-tool lookup) or RESTIC_PASSWORD_FILE,
kopia through KOPIA_PASSWORD in its environment only.

WHEN -- backup.timer, daily and Persistent (a day the computer was off runs at
the next start), enabled by `schedule on` (Settings turns it on after the
repository is made). backup.service runs it at the lowest CPU and disk
priority (Nice 19, idle I/O) inside railguard's heavy.slice, so it never gets
in the way of what you are doing. A failed run is a critical notification
with the reason; no good backup in WARN_DAYS days is one too (once a day at
most), and doctor.py and the morning brief say so as well.

THE LAST RUN is kept in $XDG_STATE_HOME/hypr/backup/state.json (when, how it
went, what it added, the repository's size), which status, doctor.py and
brief.py read without running restic.

Neither restic nor kopia installed: status says so and names the package
(`sudo dnf install restic`); nothing else runs.
"""
import fcntl
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
CONF = os.environ.get("HYPR_BACKUP_CONF") or os.path.join(
    os.environ.get("XDG_CONFIG_HOME") or os.path.join(HOME, ".config"), "hypr", "backup.conf")
STATE_DIR = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.join(HOME, ".local", "state"),
                         "hypr", "backup")
STATE = os.path.join(STATE_DIR, "state.json")
LOCK = os.path.join(STATE_DIR, ".lock")
KOPIA_CONFIG = os.path.join(STATE_DIR, "kopia.config")    # kopia's own connection file, kept apart
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import desk_common  # noqa: E402  (notify: the notification, through scripts/notify)
APP = "Backup"
TIMER = "backup.timer"
SECRET_ATTRS = ("service", "hypr-backup")
ENGINES = ("restic", "kopia")
PACKAGES = {"restic": "restic", "kopia": "kopia"}    # Fedora's package for each
WARN_DAYS = 7                   # no good backup for this long: warn (notification, doctor, brief)
BRIEF_DAYS = 2                  # the morning brief mentions a backup older than this
NOTIFY_EVERY_S = 20 * 3600      # the "no backup for a week" toast, once a day at most

DEFAULT_INCLUDE = ["~/Documents", "~/Pictures", "~/Desktop", "~/Music", "~/.config", "~/.ssh"]
DEFAULT_EXCLUDE = ["~/.cache", "node_modules", "__pycache__", ".venv", "*.tmp", "*.part",
                   "~/.config/*/Cache", "~/.config/*/GPUCache", "~/.config/*/Code Cache",
                   "~/.config/hypr/backup.pass"]
DEFAULTS = {"engine": "auto", "repo": "", "password": "keyring",
            "keep_daily": 7, "keep_weekly": 4, "keep_monthly": 6}
KEEPS = ("keep_daily", "keep_weekly", "keep_monthly")


# -- the settings (pure) ----------------------------------------------------------------
def parse_conf(text):
    """backup.conf's text -> the settings dict, defaults filled in. include /
    exclude are lists (the defaults only when the file names none at all);
    unknown keys and bad numbers are ignored."""
    conf = dict(DEFAULTS)
    include, exclude, seen = [], [], set()
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        seen.add(key)
        if key == "include" and value and value not in include:
            include.append(value)
        elif key == "exclude" and value and value not in exclude:
            exclude.append(value)
        elif key in KEEPS:
            try:
                conf[key] = max(0, int(value))
            except ValueError:
                pass
        elif key in ("engine", "repo", "password"):
            conf[key] = value
    conf["include"] = include if "include" in seen else list(DEFAULT_INCLUDE)
    conf["exclude"] = exclude if "exclude" in seen else list(DEFAULT_EXCLUDE)
    if conf["engine"] not in ("auto",) + ENGINES:
        conf["engine"] = "auto"
    return conf


def render_conf(conf):
    """The settings dict -> backup.conf's text (what parse_conf reads back)."""
    lines = ["# backup.py's settings (Settings > Storage > Backup); `backup.py --help` has them all.",
             f"engine={conf.get('engine', 'auto')}", f"repo={conf.get('repo', '')}",
             f"password={conf.get('password', 'keyring')}"]
    lines += [f"{k}={conf.get(k, DEFAULTS[k])}" for k in KEEPS]
    lines += [f"include={p}" for p in conf.get("include", [])]
    lines += [f"exclude={p}" for p in conf.get("exclude", [])]
    if not conf.get("include"):
        lines.append("include=")    # an empty list stays empty (not the defaults)
    if not conf.get("exclude"):
        lines.append("exclude=")
    return "\n".join(lines) + "\n"


def check_setting(key, value):
    """The value to store for `set KEY VALUE`, or ValueError saying why not."""
    value = (value or "").strip()
    if key == "engine":
        if value not in ("auto",) + ENGINES:
            raise ValueError("engine is auto, restic or kopia")
        return value
    if key == "repo":
        if "\n" in value:
            raise ValueError("the repository is one line")
        return value
    if key == "password":
        if value == "keyring" or (value.startswith("file:") and len(value) > 5):
            return value
        raise ValueError("password is keyring or file:PATH")
    if key in KEEPS:
        if not value.isdigit() or int(value) > 1000:
            raise ValueError(f"{key} is a number of snapshots, 0-1000")
        return int(value)
    raise ValueError(f"unknown setting {key!r}")


def edit_list(items, action, value):
    """include / exclude: add (once, at the end) or remove an entry."""
    value = (value or "").strip()
    items = [i for i in items if i != value]
    if action == "add" and value:
        items.append(value)
    return items


def expand(path, home=HOME):
    """~ and ~/... to the home folder; anything else as it is."""
    if path == "~":
        return home
    if path.startswith("~/"):
        return os.path.join(home, path[2:])
    return path


def is_local(repo):
    """A plain folder (not restic's sftp:, rest:, s3:, b2:, ... or a
    `local:` prefix, which is a folder too)."""
    if repo.startswith("local:"):
        return True
    return bool(repo) and not re.match(r"^[a-z][a-z0-9]*:", repo)


def local_path(repo, home=HOME):
    """The folder of a local repository, else None."""
    if not is_local(repo):
        return None
    return expand(repo[6:] if repo.startswith("local:") else repo, home)


def pick_engine(conf, installed):
    """The engine to use: the chosen one when installed; auto = restic, else
    kopia; None when there is none."""
    want = conf.get("engine", "auto")
    if want in ENGINES:
        return want if want in installed else None
    return next((e for e in ENGINES if e in installed), None)


def password_file_problem(mode):
    """A password file anyone but you can read is refused: the reason, or ""."""
    if mode is None:
        return "the password file does not exist"
    if mode & 0o077:
        return f"the password file can be read by others (mode {stat.S_IMODE(mode):o}); chmod 600 it"
    return ""


def secret_lookup_argv(repo):
    return ["secret-tool", "lookup", *SECRET_ATTRS, "repo", repo]


def secret_store_argv(repo):
    return ["secret-tool", "store", f"--label=Backup repository {repo}", *SECRET_ATTRS, "repo", repo]


def problems(conf, installed, password_ok=True, file_mode=None):
    """What stands between these settings and a backup, in plain words
    (empty: ready). installed: the engines found."""
    out = []
    engine = pick_engine(conf, installed)
    if not installed:
        out.append("neither restic nor kopia is installed: sudo dnf install restic")
    elif engine is None:
        out.append(f"{conf['engine']} is not installed: sudo dnf install {PACKAGES[conf['engine']]}")
    if not conf.get("repo"):
        out.append("no repository chosen yet")
    elif engine == "kopia" and not is_local(conf["repo"]):
        out.append("kopia here backs up to a folder only; use restic for sftp: / rest: / s3: URLs")
    if not conf.get("include"):
        out.append("nothing is included")
    pw = conf.get("password", "keyring")
    if pw.startswith("file:"):
        why = password_file_problem(file_mode)
        if why:
            out.append(why)
    elif conf.get("repo") and not password_ok:
        out.append("no password stored for this repository yet")
    return out


# -- the commands (pure: argv and environment) ------------------------------------------
def engine_env(engine, conf, environ, password=None):
    """The environment restic / kopia runs with: the repository and how it
    gets the password, never the password on a command line. password: the
    secret itself, only for kopia with the keyring (looked up by the caller)."""
    env = dict(environ)
    pw = conf.get("password", "keyring")
    if engine == "restic":
        env["RESTIC_REPOSITORY"] = expand(conf["repo"])
        env.pop("RESTIC_PASSWORD", None)
        if pw.startswith("file:"):
            env["RESTIC_PASSWORD_FILE"] = expand(pw[5:])
            env.pop("RESTIC_PASSWORD_COMMAND", None)
        else:
            env["RESTIC_PASSWORD_COMMAND"] = shlex.join(secret_lookup_argv(conf["repo"]))
            env.pop("RESTIC_PASSWORD_FILE", None)
    else:
        env["KOPIA_CHECK_FOR_UPDATES"] = "false"
        if password is not None:
            env["KOPIA_PASSWORD"] = password
    return env


def kopia(*args):
    return ["kopia", f"--config-file={KOPIA_CONFIG}", *args]


def backup_argv(engine, conf, home=HOME):
    """The backup command for the included folders that exist."""
    paths = [expand(p, home) for p in conf.get("include", [])]
    paths = [p for p in paths if os.path.exists(p)]
    if engine == "restic":
        argv = ["restic", "backup", "--json", "--one-file-system", "--exclude-caches", "--tag", "hypr-backup"]
        for pattern in conf.get("exclude", []):
            argv += ["--exclude", expand(pattern, home)]
        return argv + paths
    return kopia("snapshot", "create", "--json", *paths)


def forget_argv(engine, conf):
    """Thin old snapshots to the keep policy (and free their space)."""
    keep = [(k, int(conf.get(k, DEFAULTS[k]))) for k in KEEPS]
    if engine == "restic":
        argv = ["restic", "forget", "--prune", "--tag", "hypr-backup", "--group-by", "host,tags"]
        for key, n in keep:
            if n:
                argv += [f"--keep-{key[5:]}", str(n)]
        return argv if len(argv) > 7 else None      # a policy of nothing kept is never run
    args = ["policy", "set", "--global"]
    for key, n in keep:
        args += [f"--keep-{key[5:]}", str(n)]
    for pattern in conf.get("exclude", []):
        args += ["--add-ignore", expand(pattern)]
    return kopia(*args)


def init_argv(engine, conf):
    if engine == "restic":
        return ["restic", "init"]
    return kopia("repository", "create", "filesystem", f"--path={local_path(conf['repo'])}")


def connect_argv(conf):
    return kopia("repository", "connect", "filesystem", f"--path={local_path(conf['repo'])}")


def snapshots_argv(engine):
    if engine == "restic":
        return ["restic", "snapshots", "--json", "--tag", "hypr-backup"]
    return kopia("snapshot", "list", "--json", "--all")


def stats_argv(engine):
    if engine == "restic":
        return ["restic", "stats", "--json", "--mode", "raw-data"]
    return None


# -- reading their answers (pure) -------------------------------------------------------
def parse_summary(engine, out):
    """What a backup did, from its --json output: {"added", "processed",
    "files", "snapshot"} (missing values None)."""
    got = {"added": None, "processed": None, "files": None, "snapshot": None}
    if engine == "restic":
        for line in (out or "").splitlines():
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if isinstance(msg, dict) and msg.get("message_type") == "summary":
                got.update(added=msg.get("data_added"), processed=msg.get("total_bytes_processed"),
                           files=msg.get("total_files_processed"), snapshot=msg.get("snapshot_id"))
        return got
    try:
        data = json.loads(out or "null")
    except ValueError:
        return got
    for snap in data if isinstance(data, list) else [data]:
        if isinstance(snap, dict):
            summ = (snap.get("rootEntry") or {}).get("summ") or {}
            got["snapshot"] = snap.get("id") or got["snapshot"]
            got["processed"] = (got["processed"] or 0) + (summ.get("size") or 0)
            got["files"] = (got["files"] or 0) + (summ.get("files") or 0)
    return got


def parse_snapshots(engine, out):
    """[{"id", "time", "paths", "host"}], newest first."""
    try:
        data = json.loads(out or "[]")
    except ValueError:
        return []
    snaps = []
    for s in data if isinstance(data, list) else []:
        if not isinstance(s, dict):
            continue
        if engine == "restic":
            snaps.append({"id": s.get("short_id") or (s.get("id") or "")[:8], "time": s.get("time") or "",
                          "paths": s.get("paths") or [], "host": s.get("hostname") or ""})
        else:
            src = s.get("source") or {}
            snaps.append({"id": (s.get("id") or "")[:8], "time": s.get("startTime") or "",
                          "paths": [src.get("path")] if src.get("path") else [], "host": src.get("host") or ""})
    snaps.sort(key=lambda s: s["time"], reverse=True)
    return snaps


def parse_stats(out):
    """The repository's size on disk from `restic stats --json --mode raw-data`."""
    try:
        data = json.loads(out or "null")
    except ValueError:
        return None
    return data.get("total_size") if isinstance(data, dict) else None


def last_error(text, limit=300):
    """The few lines of a failure worth showing: restic's "Fatal:" line when
    there is one, else the last lines."""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    fatal = [line for line in lines if line.lower().startswith(("fatal", "error"))]
    pick = fatal[-2:] if fatal else lines[-3:]
    return " ".join(pick)[:limit] or "it stopped without saying why"


# -- age and health (pure) --------------------------------------------------------------
def human(size):
    """Bytes in decimal units ("1.2 GB"), "" for None."""
    if size is None:
        return ""
    size = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1000 or unit == "TB":
            return f"{size:.0f} {unit}" if unit in ("B", "KB") else f"{size:.1f} {unit}"
        size /= 1000
    return ""


def age_text(seconds):
    """"3 min ago", "5 h ago", "2 days ago"; "never" for None."""
    if seconds is None:
        return "never"
    seconds = max(0, int(seconds))
    if seconds < 3600:
        return f"{max(1, seconds // 60)} min ago"
    if seconds < 2 * 86400:
        return f"{seconds // 3600} h ago"
    return f"{seconds // 86400} days ago"


def health(state, configured, now):
    """(level, text) for doctor.py: None when no backup is set up."""
    if not configured:
        return None
    last_ok = state.get("last_ok")
    if state.get("last_run") and not state.get("ok"):
        why = state.get("error") or "it failed"
        since = f"; last good one {age_text(now - last_ok)}" if last_ok else "; none has worked yet"
        return "warn", f"the last backup failed: {why[:100]}{since}"
    if not last_ok:
        return "warn", "set up, but no backup has run yet"
    age = now - last_ok
    if age > WARN_DAYS * 86400:
        return "warn", f"no backup for {int(age // 86400)} days"
    size = f", repository {human(state.get('repo_size'))}" if state.get("repo_size") else ""
    return "ok", f"last backup {age_text(age)}{size}"


def brief_text(state, configured, now):
    """The morning brief's line: [] when backups are fine or not set up."""
    if not configured:
        return []
    last_ok = state.get("last_ok")
    if state.get("last_run") and not state.get("ok"):
        return [f"Backup failed {age_text(now - state['last_run'])}: {(state.get('error') or '')[:80]}"
                "  (Settings > Storage > Backup)"]
    if not last_ok:
        return ["Backup is set up but has not run yet  (Settings > Storage > Backup: Run now)"]
    if now - last_ok > BRIEF_DAYS * 86400:
        return [f"Last backup {age_text(now - last_ok)}  (Settings > Storage > Backup)"]
    return []


def stale_due(state, now):
    """Is the "no backup for a week" toast due: a backup is overdue and the
    last such toast is more than NOTIFY_EVERY_S old."""
    last_ok = state.get("last_ok") or state.get("since")
    if not last_ok or now - last_ok <= WARN_DAYS * 86400:
        return False
    return now - (state.get("stale_notified") or 0) > NOTIFY_EVERY_S


def restore_hint(engine, conf, today):
    """The commands that get files back, filled in."""
    target = f"~/Restored-{today}"
    if engine == "kopia":
        return "\n".join([
            "List the snapshots:   backup.py snapshots",
            f"Restore one:          kopia --config-file={KOPIA_CONFIG} snapshot restore <ID> {target}",
            f"Browse them:          kopia --config-file={KOPIA_CONFIG} mount all ~/Backup-browse",
            "The password: secret-tool lookup service hypr-backup repo <repo> (or your password file)."])
    env = (f"export RESTIC_REPOSITORY={shlex.quote(conf.get('repo') or '<repo>')}\n"
           + (f"export RESTIC_PASSWORD_FILE={shlex.quote(expand(conf['password'][5:]))}"
              if conf.get("password", "").startswith("file:") else
              f"export RESTIC_PASSWORD_COMMAND={shlex.quote(shlex.join(secret_lookup_argv(conf.get('repo') or '<repo>')))}"))
    return "\n".join([
        "In a terminal, first:", env, "",
        "Everything from the newest snapshot, into a new folder (nothing is overwritten):",
        f"  restic restore latest --target {target}",
        "One folder or file only:",
        f"  restic restore latest --target {target} --include ~/Documents/report.odt",
        "Browse every snapshot as folders (Ctrl+C to stop):",
        "  mkdir -p ~/Backup-browse && restic mount ~/Backup-browse",
        "The snapshots:  restic snapshots"])


# -- files and processes ----------------------------------------------------------------
def load(path=None):
    try:
        with open(path or CONF, encoding="utf-8") as handle:
            return parse_conf(handle.read())
    except OSError:
        return parse_conf("")


def save(conf, path=None):
    path = path or CONF
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(render_conf(conf))
    os.replace(tmp, path)


def load_state(path=None):
    try:
        with open(path or STATE) as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(state, path=None):
    path = path or STATE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as handle:
        json.dump(state, handle, indent=1)
    os.replace(tmp, path)


def installed():
    return [e for e in ENGINES if shutil.which(e)]


def sh(argv, env=None, timeout=None, stdin=None):
    """(rc, stdout, stderr); 127 when the program is missing."""
    try:
        r = subprocess.run(argv, capture_output=True, text=True, env=env, timeout=timeout, input=stdin)
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError as exc:
        return 127, "", str(exc)
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, "", str(exc)


def password_stored(repo):
    if not repo or not shutil.which("secret-tool"):
        return False
    rc, out, _ = sh(secret_lookup_argv(repo), timeout=10)
    return rc == 0 and bool(out)


def file_mode(conf):
    pw = conf.get("password", "keyring")
    if not pw.startswith("file:"):
        return None
    try:
        return os.stat(expand(pw[5:])).st_mode
    except OSError:
        return None


def readiness(conf):
    """(engine or None, the problems list), for status and run."""
    found = installed()
    pw = conf.get("password", "keyring")
    ok = password_stored(conf.get("repo")) if pw == "keyring" and conf.get("repo") else True
    return pick_engine(conf, found), problems(conf, found, ok, file_mode(conf))


def is_configured(conf, found=None):
    """Set up enough for the timer to try: a repository and an engine."""
    found = installed() if found is None else found
    return bool(conf.get("repo")) and pick_engine(conf, found) is not None


def secret(conf):
    """kopia with the keyring: the password itself, for its environment."""
    if conf.get("password", "keyring") != "keyring":
        try:
            with open(expand(conf["password"][5:])) as handle:
                return handle.read().strip()
        except OSError:
            return None
    rc, out, _ = sh(secret_lookup_argv(conf["repo"]), timeout=10)
    return out.strip() if rc == 0 else None


def env_for(engine, conf):
    return engine_env(engine, conf, os.environ, secret(conf) if engine == "kopia" else None)


def notify(summary, body="", urgency="normal", icon="drive-harddisk"):
    desk_common.notify(summary, body, app=APP, urgency=urgency, icon=icon, timeout=10)


def timer_state():
    _, out, _ = sh(["systemctl", "--user", "show", TIMER, "-p", "UnitFileState,ActiveState,NextElapseUSecRealtime"],
                   timeout=5)
    props = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    return {"enabled": props.get("UnitFileState") == "enabled", "active": props.get("ActiveState") == "active",
            "next": props.get("NextElapseUSecRealtime") or None}


def status():
    conf = load()
    engine, probs = readiness(conf)
    state = load_state()
    now = time.time()
    found = installed()
    level = health(state, is_configured(conf, found), now)
    return {"conf": conf, "conf_path": CONF, "engine": engine, "installed": found,
            "package": None if found else PACKAGES["restic"], "problems": probs,
            "configured": is_configured(conf, found), "local": local_path(conf["repo"]) if conf["repo"] else None,
            "state": state, "health": list(level) if level else None,
            "last_ok_text": age_text(now - state["last_ok"]) if state.get("last_ok") else "never",
            "repo_size_text": human(state.get("repo_size")), "timer": timer_state(),
            "restore_hint": restore_hint(engine or "restic", conf, time.strftime("%Y-%m-%d"))}


def status_text(data):
    conf, state = data["conf"], data["state"]
    lines = [f"engine      {data['engine'] or 'none installed'}",
             f"repository  {conf['repo'] or '(not chosen)'}",
             f"last good   {data['last_ok_text']}"
             + (f"  ·  repository {data['repo_size_text']}" if data["repo_size_text"] else ""),
             f"daily       {'on' if data['timer']['enabled'] else 'off'}",
             f"includes    {', '.join(conf['include']) or '(nothing)'}",
             f"excludes    {', '.join(conf['exclude']) or '(nothing)'}",
             "keeps       " + ", ".join(f"{conf[k]} {k[5:]}" for k in KEEPS)]
    if state.get("last_run") and not state.get("ok"):
        lines.append(f"last run    FAILED: {state.get('error')}")
    lines += [f"problem     {p}" for p in data["problems"]]
    return "\n".join(lines)


# -- running ----------------------------------------------------------------------------
def run_backup(timer=False):
    """One backup, the thinning, the size; the state written either way.
    Returns the exit code."""
    conf = load()
    found = installed()
    if timer and not is_configured(conf, found):
        print("backup: not set up, nothing to do")
        return 0
    os.makedirs(STATE_DIR, exist_ok=True)
    lock = open(LOCK, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("backup: one is already running")
        return 0
    engine, probs = readiness(conf)
    state = load_state()
    state.setdefault("since", time.time())        # the stale warning counts from setup when none ever worked
    start = time.time()
    state["last_run"] = start
    error = probs[0] if probs else None
    local = local_path(conf["repo"]) if conf.get("repo") else None
    if not error and local and not os.path.isdir(local):
        error = f"the repository folder {local} is not there (a drive not plugged in?)"
    summary = {}
    if not error:
        env = env_for(engine, conf)
        policy = forget_argv(engine, conf)
        if engine == "kopia":
            sh(connect_argv(conf), env=env, timeout=120)
            # kopia's keep policy and ignores are read by the snapshot itself
            # (it thins as it goes), so they are set first.
            prc, pout, perr = sh(policy, env=env, timeout=120)
            policy = None
            if prc != 0:
                state["warning"] = "the keep policy was not set: " + last_error(perr or pout, 160)
        rc, out, err = sh(backup_argv(engine, conf), env=env)
        # restic exits 3 when some files could not be read: the snapshot is made.
        if rc not in (0, 3):
            error = last_error(err or out)
        else:
            summary = parse_summary(engine, out)
            if rc == 3:
                state["warning"] = "some files could not be read: " + last_error(err, 160)
            elif engine == "restic":
                state.pop("warning", None)
            if policy:
                prc, pout, perr = sh(policy, env=env)
                if prc != 0:
                    state["warning"] = "old snapshots were not thinned: " + last_error(perr or pout, 160)
            stats = stats_argv(engine)
            if stats:
                src, sout, _ = sh(stats, env=env, timeout=600)
                if src == 0:
                    state["repo_size"] = parse_stats(sout)
    state["duration"] = round(time.time() - start)
    state["engine"] = engine
    if error:
        state.update(ok=False, error=error)
    else:
        state.update(ok=True, error=None, last_ok=time.time(), **{k: v for k, v in summary.items() if v is not None})
    save_state(state)
    if error:
        notify("Backup failed", error + "\n\nSettings > Storage > Backup", "critical", "dialog-warning")
    if error:
        print(f"backup: failed: {error}", file=sys.stderr)
        return 1
    print(f"backup: done in {state['duration']} s, added {human(state.get('added')) or '?'}"
          + (f"; {state['warning']}" if state.get("warning") else ""))
    return 0


def warn_if_stale():
    """The "no backup for a week" toast (once a day at most); run by the
    timer's runs, so a repository that stays unreachable still gets one."""
    conf = load()
    if not is_configured(conf):
        return
    state = load_state()
    now = time.time()
    if stale_due(state, now):
        days = int((now - (state.get("last_ok") or state.get("since") or now)) // 86400)
        notify("No backup for a week", f"The last good backup was {days} days ago."
               "\nSettings > Storage > Backup: Run now", "critical", "dialog-warning")
        state["stale_notified"] = now
        save_state(state)


def init():
    conf = load()
    engine, probs = readiness(conf)
    if engine is None or not conf.get("repo") or probs:
        sys.exit(f"backup: cannot create it yet: {'; '.join(probs) or 'no engine'}")
    local = local_path(conf["repo"])
    if local:
        os.makedirs(local, exist_ok=True)
    rc, out, err = sh(init_argv(engine, conf), env=env_for(engine, conf), timeout=300)
    if rc != 0:
        sys.exit(f"backup: could not create the repository: {last_error(err or out)}")
    print(f"backup: repository created at {conf['repo']}")
    schedule(True)


def schedule(on):
    verb = ["enable", "--now"] if on else ["disable", "--now"]
    rc, _, err = sh(["systemctl", "--user", *verb, TIMER], timeout=20)
    if rc != 0:
        sys.exit(f"backup: {err.strip()}")


def snapshots():
    conf = load()
    engine, _ = readiness(conf)
    if engine is None or not conf.get("repo"):
        return None, "no backup set up"
    env = env_for(engine, conf)
    if engine == "kopia":
        sh(connect_argv(conf), env=env, timeout=120)
    rc, out, err = sh(snapshots_argv(engine), env=env, timeout=300)
    if rc != 0:
        return None, last_error(err or out)
    return parse_snapshots(engine, out), None


# -- doctor.py and brief.py --------------------------------------------------------------
def doctor_check(now=None):
    """(level, text) or None, from the saved state (no restic run)."""
    return health(load_state(), is_configured(load()), now or time.time())


def brief_lines(now=None):
    return brief_text(load_state(), is_configured(load()), now or time.time())


def main(argv):
    cmd = argv[0] if argv else "status"
    as_json = "--json" in argv
    if cmd == "status":
        data = status()
        print(json.dumps(data, indent=1) if as_json else status_text(data))
    elif cmd == "run":
        timer = "--timer" in argv
        code = run_backup(timer)
        if timer:
            warn_if_stale()
        sys.exit(code)
    elif cmd == "configured":
        sys.exit(0 if is_configured(load()) else 1)
    elif cmd == "snapshots":
        snaps, error = snapshots()
        if as_json:
            print(json.dumps({"snapshots": snaps or [], "error": error}))
        elif error:
            sys.exit(f"backup: {error}")
        else:
            for s in snaps:
                print(f"{s['id']}  {s['time'][:19].replace('T', ' ')}  {s['host']}  {', '.join(s['paths'])}")
    elif cmd == "restore-hint":
        conf = load()
        engine, _ = readiness(conf)
        print(restore_hint(engine or "restic", conf, time.strftime("%Y-%m-%d")))
    elif cmd == "init":
        init()
    elif cmd == "set" and len(argv) == 3:
        conf = load()
        try:
            conf[argv[1]] = check_setting(argv[1], argv[2])
        except ValueError as exc:
            sys.exit(f"backup: {exc}")
        save(conf)
    elif cmd in ("include", "exclude") and len(argv) == 3 and argv[1] in ("add", "remove"):
        conf = load()
        conf[cmd] = edit_list(conf[cmd], argv[1], argv[2])
        save(conf)
    elif cmd == "password" and argv[1:] == ["store"]:
        conf = load()
        if not conf.get("repo"):
            sys.exit("backup: choose the repository first")
        if not shutil.which("secret-tool"):
            sys.exit("backup: secret-tool is missing (sudo dnf install libsecret); use password=file:PATH")
        secret_text = sys.stdin.read().rstrip("\n")
        if not secret_text:
            sys.exit("backup: an empty password")
        rc, _, err = sh(secret_store_argv(conf["repo"]), stdin=secret_text, timeout=30)
        if rc != 0:
            sys.exit(f"backup: the keyring said no: {err.strip()}")
    elif cmd == "schedule" and argv[1:2] in (["on"], ["off"]):
        schedule(argv[1] == "on")
    elif cmd == "open":
        local = local_path(load().get("repo", ""))
        if not local or not os.path.isdir(local):
            sys.exit("backup: the repository is not a folder here")
        subprocess.Popen(["xdg-open", local], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
