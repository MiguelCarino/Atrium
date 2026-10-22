#!/usr/bin/env python3
"""Desktop settings: where YOUR things are, the few paths the desktop cannot
guess the same for everyone. One small key=value file,
~/.config/hypr/desktop.conf (same style as privacy.conf / automount.conf):

    projects=~/Projects     your projects folder: the git repos in it are the
                            git pill and panel, the project contexts, the
                            brief's "what you worked on" and commits, the
                            assistant's and voice's "repo X", the search
                            index's code files. Unset: the first of
                            CANDIDATES that exists (~/Github, ~/GitHub,
                            ~/Projects, ~/projects, ~/src, ~/code, ~/Code,
                            ~/repos, ~/git), else ~/Projects (made by no one:
                            the features just find no repos until it exists)
    dotfiles=~/dotfiles     your dotfiles repo, one with a sync.sh that copies
                            the live config into it (`sync.sh --check` prints
                            the drift as JSON). The doctor's dotfiles check,
                            the git panel's drift row and the daily
                            dotfiles-backup.sh use it. Unset, or no sync.sh
                            there: those are skipped quietly

A leading ~ is your home; a relative path is taken from home too. Comments
(#), blanks and unknown keys are kept as they are when a key is written.

    desktop_conf.py get projects|dotfiles   the resolved path ("" = none)
    desktop_conf.py set projects|dotfiles PATH   write it ("" unsets it)
    desktop_conf.py show                    every key, resolved, as JSON

$HYPR_DESKTOP_CONF points it at another file (the tests do).
"""

import json
import os
import sys
import tempfile

HOME = os.path.expanduser("~")
CONFIG_HOME = os.environ.get("XDG_CONFIG_HOME") or os.path.join(HOME, ".config")
CONF = os.environ.get("HYPR_DESKTOP_CONF") or os.path.join(CONFIG_HOME, "hypr", "desktop.conf")
KEYS = ("projects", "dotfiles")
CANDIDATES = ("Github", "GitHub", "Projects", "projects", "src", "code", "Code", "repos", "git")
FALLBACK = "Projects"
HEADER = ("# Desktop settings (scripts/desktop_conf.py; its docstring explains).\n"
          "# projects = your projects folder; dotfiles = your dotfiles repo (with a sync.sh).\n")


def parse(text):
    """key=value lines; comments, blanks and junk skipped, last one wins."""
    conf = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        conf[key.strip()] = value.strip()
    return conf


def load(path=None):
    """desktop.conf as a dict ({} when it is missing or unreadable)."""
    try:
        with open(path or CONF) as handle:
            return parse(handle.read())
    except OSError:
        return {}


def expand(value, home=HOME):
    """"~/x" / "x" / "/abs/x" -> an absolute path ("" stays "")."""
    value = (value or "").strip()
    if not value:
        return ""
    if value == "~" or value.startswith("~/"):
        value = home + value[1:]
    return os.path.normpath(os.path.join(home, value))


def projects_dir(path=None, home=HOME):
    """Your projects folder, always a path (it may not exist yet)."""
    chosen = expand(load(path).get("projects"), home)
    if chosen:
        return chosen
    for name in CANDIDATES:
        if os.path.isdir(os.path.join(home, name)):
            return os.path.join(home, name)
    return os.path.join(home, FALLBACK)


def dotfiles_repo(path=None, home=HOME):
    """Your dotfiles repo when it is set AND has a sync.sh, else None."""
    repo = expand(load(path).get("dotfiles"), home)
    return repo if repo and os.path.isfile(os.path.join(repo, "sync.sh")) else None


def tilde(path, home=HOME):
    """/home/you/x -> ~/x, for text on screen."""
    return "~" + path[len(home):] if path == home or path.startswith(home + "/") else path


def set_key(key, value, path=None):
    """Write one key, keeping every other line (comments too); "" removes it."""
    if key not in KEYS:
        raise ValueError(f"not a setting: {key!r} (one of {', '.join(KEYS)})")
    path = path or CONF
    value = (value or "").strip()
    try:
        with open(path) as handle:
            lines = handle.read().splitlines()
    except OSError:
        lines = HEADER.splitlines()
    out, done = [], False
    for line in lines:
        if line.strip().partition("=")[0].strip() == key and not line.strip().startswith("#"):
            if value and not done:
                out.append(f"{key}={value}")
            done = True
            continue
        out.append(line)
    if value and not done:
        out.append(f"{key}={value}")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-")
    with os.fdopen(fd, "w") as handle:
        handle.write("\n".join(out) + "\n")
    os.replace(tmp, path)


def resolved(path=None):
    return {"projects": projects_dir(path), "dotfiles": dotfiles_repo(path) or "",
            "projects_set": bool(load(path).get("projects")), "conf": path or CONF}


def main(argv):
    cmd = argv[0] if argv else "show"
    if cmd == "get" and len(argv) == 2 and argv[1] in KEYS:
        print(resolved()[argv[1]])
    elif cmd == "set" and len(argv) >= 2 and argv[1] in KEYS:
        set_key(argv[1], " ".join(argv[2:]))
        print(resolved()[argv[1]])
    elif cmd == "show":
        print(json.dumps(resolved()))
    else:
        print(__doc__.strip(), file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main(sys.argv[1:])
