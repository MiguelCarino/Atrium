#!/usr/bin/env python3
"""Git pill (custom/repos): the git logo, coloured by the state of the repos
in your projects folder (projects= in ~/.config/hypr/desktop.conf, see
hypr/scripts/desktop_conf.py) -- and what its panel (repos_panel.py) runs.

    repos.py              one JSON line for waybar (always shown: the logo, plus
                          the number of changed files when there are any)
    repos.py scan         the full scan as JSON
    repos.py fetch        `git fetch` every repo (network), then scan
    repos.py pull PATH    fast-forward-only pull of one repo
    repos.py site PATH    the repo's website, if it has one (see website())
    repos.py preview PATH serve the repo's site on localhost as it is on disk
                          (uncommitted changes included) and print the URL
    repos.py preview-stop PATH
    repos.py serve DIR PORT   the preview server itself (what preview starts)
    repos.py commit PATH  interactive, in a terminal: show the changes, ask
                          for a message, commit everything as you (your global
                          user.name / user.email -- no co-author lines), then
                          offer to push. With nothing to commit but commits
                          not pushed, it goes straight to the push question.

One `git status --porcelain=v2 --branch` per repo gives everything: the
changed and untracked files, and the "# branch.ab +A -B" header with ahead /
behind against the upstream. No `git fetch` -- nothing here touches the
network, so "behind" is only as fresh as your last fetch or pull, and the
pill is about what YOU have not pushed, which needs no network to know.

Runs at idle priority, eight repos at a time; ~50 repos take well under a
second warm. The last scan is kept in $XDG_RUNTIME_DIR/repos.json so the panel
opens instantly instead of rescanning.

The dotfiles repo (dotfiles= in the same file; none set: skipped) gets one
more number: "drift", the files in ~ that differ
from its copy (dotfiles.py, i.e. `sync.sh --check`, a dry-run rsync). The repo
is a copy of ~/.config, not symlinks, so drift is work that is not even in the
repo yet -- it counts towards the logo's colour like uncommitted changes, and
the panel offers Sync for it.

`fetch` is the only network call, and only when asked (the panel's Rescan):
after it, "behind" is real and Pull has something to do.

Classes: clean (dim logo), dirty (uncommitted only), unpushed (commits that
exist only on this machine -- the one that matters if the disk dies).
"""

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dotfiles  # noqa: E402  (it also puts hypr/scripts on the path)
import desktop_conf  # noqa: E402

ROOT = desktop_conf.projects_dir()      # your projects folder
CACHE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "repos.json")
# git-alt, which lives in the Brands font, not the Solid one the bar uses.
ICON = "<span font_family='Font Awesome 6 Brands'>\uf841</span>"
QUIET_GIT = dict(os.environ, GIT_TERMINAL_PROMPT="0")    # never hang on a prompt


def repo_dirs():
    try:
        names = sorted(os.listdir(ROOT), key=str.lower)
    except OSError:
        return []
    return [os.path.join(ROOT, n) for n in names
            if os.path.isdir(os.path.join(ROOT, n, ".git"))]


def website(path):
    """The repo's website, from its own files (no network): a GitHub Pages
    CNAME (at the top, or in docs/ when Pages publishes from there), else
    package.json's "homepage". "" when it has neither."""
    for name in ("CNAME", "docs/CNAME"):
        try:
            with open(os.path.join(path, name)) as handle:
                host = handle.readline().strip()
        except (OSError, UnicodeDecodeError):
            continue
        # A CNAME holds one bare host name; anything else is not a site.
        if host and " " not in host and "/" not in host.split("://")[-1]:
            return host if "://" in host else f"https://{host}"
    try:
        with open(os.path.join(path, "package.json")) as handle:
            home = json.load(handle).get("homepage", "")
    except (OSError, ValueError, AttributeError):
        return ""
    return home if isinstance(home, str) and home.startswith(("https://", "http://")) else ""


def site_dir(path):
    """Where the repo's static site lives: the folder with the CNAME (the top,
    or docs/ for Pages-from-docs), as long as it has an index.html. "" for a
    repo with no static site to preview."""
    for sub in ("", "docs"):
        folder = os.path.join(path, sub) if sub else path
        if (os.path.isfile(os.path.join(folder, "CNAME"))
                and os.path.isfile(os.path.join(folder, "index.html"))):
            return folder
    return ""


# Local previews: one transient user service per repo (systemd-run), so a
# preview outlives the panel that started it, shows in `systemctl --user`,
# and stops by itself after PREVIEW_MAX. Bound to 127.0.0.1 only.
PREVIEWS = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "repo-previews.json")
PREVIEW_MAX = "2h"


def _unit(path):
    name = "".join(c if c.isalnum() else "-" for c in os.path.basename(path))
    return f"repo-preview-{name}.service"


def _previews():
    try:
        with open(PREVIEWS) as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def previewing(path):
    """The localhost URL when this repo's preview is running, else ""."""
    port = _previews().get(path)
    if not port:
        return ""
    active = subprocess.run(["systemctl", "--user", "is-active", "--quiet", _unit(path)])
    return f"http://localhost:{port}/" if active.returncode == 0 else ""


def _free_port(path):
    import socket
    import zlib
    # The same port for the same repo each time where possible, so the
    # browser's history and open tabs keep working across previews.
    start = 8100 + zlib.crc32(os.path.basename(path).encode()) % 800
    for port in list(range(start, 8900)) + list(range(8100, start)):
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    return 0


def preview(path):
    """(ok, URL or what went wrong). Starts the server if it is not running."""
    url = previewing(path)
    if url:
        return True, url
    folder = site_dir(path)
    if not folder:
        return False, "no static site here (no CNAME next to an index.html)"
    port = _free_port(path)
    if not port:
        return False, "no free port between 8100 and 8899"
    unit = _unit(path)
    subprocess.run(["systemctl", "--user", "reset-failed", unit], capture_output=True)
    out = subprocess.run(
        ["systemd-run", "--user", "--quiet", "--collect", f"--unit={unit}",
         f"--description=Local preview of {os.path.basename(path)}",
         f"--property=RuntimeMaxSec={PREVIEW_MAX}",
         sys.executable, os.path.abspath(__file__), "serve", folder, str(port)],
        capture_output=True, text=True)
    if out.returncode != 0:
        return False, out.stderr.strip().splitlines()[-1] if out.stderr.strip() else "could not start"
    previews = _previews()
    previews[path] = port
    try:
        with open(PREVIEWS, "w") as handle:
            json.dump(previews, handle)
    except OSError:
        pass
    return True, f"http://localhost:{port}/"


def preview_stop(path):
    subprocess.run(["systemctl", "--user", "stop", _unit(path)], capture_output=True)


def serve(folder, port):
    """A static server for previews: http.server, but telling the browser
    never to cache, so a reload always shows the file as it is on disk now."""
    import functools
    import http.server

    class NoCache(http.server.SimpleHTTPRequestHandler):
        def end_headers(self):
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def log_message(self, *args):
            pass

    handler = functools.partial(NoCache, directory=folder)
    http.server.ThreadingHTTPServer(("127.0.0.1", port), handler).serve_forever()


def status(path):
    info = {"name": os.path.basename(path), "path": path, "branch": "?",
            "changed": 0, "untracked": 0, "ahead": 0, "behind": 0,
            "upstream": False, "error": "", "drift": 0, "website": website(path),
            "previewable": bool(site_dir(path))}
    try:
        out = subprocess.run(
            ["nice", "-n", "19", "ionice", "-c", "3", "git", "-C", path,
             "--no-optional-locks", "status", "--porcelain=v2", "--branch"],
            capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as exc:
        info["error"] = str(exc)
        return info
    if out.returncode != 0:
        info["error"] = out.stderr.strip().splitlines()[-1] if out.stderr.strip() else "git failed"
        return info
    for line in out.stdout.splitlines():
        if line.startswith("# branch.head "):
            info["branch"] = line.split(" ", 2)[2]
        elif line.startswith("# branch.upstream "):
            info["upstream"] = True
        elif line.startswith("# branch.ab "):
            ahead, behind = line.split()[2:4]
            info["ahead"], info["behind"] = int(ahead), -int(behind)
        elif line.startswith("?"):
            info["untracked"] += 1
        elif line[:1] in "12u":
            info["changed"] += 1
    return info


def needs_attention(repo):
    return bool(repo["changed"] or repo["untracked"] or repo["ahead"] or repo["behind"]
                or repo.get("drift") or not repo["upstream"] or repo["error"])


def fetch_one(path):
    try:
        subprocess.run(["nice", "-n", "19", "git", "-C", path, "fetch", "--quiet", "--prune"],
                       capture_output=True, timeout=60, env=QUIET_GIT)
    except (OSError, subprocess.SubprocessError):
        pass


def fetch():
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(fetch_one, repo_dirs()))
    return scan()


def pull(path):
    """(ok, one line of what happened)."""
    try:
        out = subprocess.run(["git", "-C", path, "pull", "--ff-only", "--quiet"],
                             capture_output=True, text=True, timeout=120, env=QUIET_GIT)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    text = (out.stderr or out.stdout).strip().splitlines()
    if out.returncode == 0:
        return True, "pulled"
    return False, text[-1] if text else "pull failed"


def commit(path):
    """Interactive; meant to run in a terminal (the panel opens kitty)."""
    os.chdir(path)
    name = subprocess.run(["git", "config", "user.name"], capture_output=True, text=True).stdout.strip()
    email = subprocess.run(["git", "config", "user.email"], capture_output=True, text=True).stdout.strip()
    print(f"\033[1m{os.path.basename(path)}\033[0m  as {name} <{email}>\n")
    subprocess.run(["git", "status", "--short", "--branch"])
    dirty = subprocess.run(["git", "status", "--porcelain"], capture_output=True,
                           text=True).stdout.strip()
    if dirty:
        try:
            message = input("\nCommit message (empty = cancel): ").strip()
        except EOFError:
            message = ""
        if not message:
            print("Cancelled; nothing committed.")
            input("\nPress Enter to close. ")
            return
        subprocess.run(["git", "add", "-A"])
        # Global git hooks, if you have any (core.hooksPath), run here -- a
        # work-hours one (hypr/scripts/workhours.py check) can ask first.
        if subprocess.run(["git", "commit", "-q", "-m", message]).returncode != 0:
            input("\nNot committed. Press Enter to close. ")
            return
        subprocess.run(["git", "log", "--oneline", "-1"])
    ahead = subprocess.run(["git", "rev-list", "--count", "@{u}..HEAD"], capture_output=True,
                           text=True)
    has_upstream = ahead.returncode == 0
    count = ahead.stdout.strip() if has_upstream else "?"
    if has_upstream and count == "0":
        print("\nNothing to push.")
    else:
        try:
            answer = input(f"\nPush{f' {count} commit(s)' if has_upstream else ' (sets upstream)'}? [y/N] ")
        except EOFError:
            answer = ""
        if answer.strip().lower() == "y":
            cmd = ["git", "push"] if has_upstream else ["git", "push", "-u", "origin", "HEAD"]
            subprocess.run(cmd)
    subprocess.run(["pkill", "-RTMIN+15", "-x", "waybar"])
    input("\nDone. Press Enter to close. ")


def scan():
    with ThreadPoolExecutor(max_workers=8) as pool:
        repos = list(pool.map(status, repo_dirs()))
    for repo in repos:
        if dotfiles.REPO and os.path.realpath(repo["path"]) == os.path.realpath(dotfiles.REPO):
            check = dotfiles.check()
            repo["drift"] = check["drift"] if check else 0
    try:
        tmp = CACHE + ".tmp"
        with open(tmp, "w") as handle:
            json.dump(repos, handle)
        os.replace(tmp, CACHE)
    except OSError:
        pass
    return repos


def describe(repo):
    bits = []
    if repo.get("drift"):
        bits.append(f"{repo['drift']} to sync from ~")
    if repo["error"]:
        bits.append(repo["error"])
    if repo["changed"]:
        bits.append(f"{repo['changed']} changed")
    if repo["untracked"]:
        bits.append(f"{repo['untracked']} new")
    if repo["ahead"]:
        bits.append(f"{repo['ahead']} unpushed")
    if not repo["upstream"] and not repo["error"]:
        bits.append("no upstream")
    if repo["behind"]:
        bits.append(f"{repo['behind']} behind")
    return ", ".join(bits)


def bar():
    repos = scan()
    todo = [r for r in repos if needs_attention(r)]
    if not todo:
        return {"text": ICON, "class": "clean",
                "tooltip": f"All {len(repos)} repos clean and pushed\n\nClick: rescan, pull, commit"}
    unpushed = [r for r in todo if r["ahead"] or (not r["upstream"] and not r["error"])]
    lines = [f"{len(todo)} of {len(repos)} repos need attention", ""]
    lines += [f"{r['name']}  ({r['branch']}):  {describe(r)}" for r in todo[:25]]
    if len(todo) > 25:
        lines.append(f"... and {len(todo) - 25} more")
    lines += ["", "Click: rescan, pull, commit   Right-click: rescan (no fetch)"]
    tooltip = "\n".join(lines).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # The number is the same change counter as the panel's header: files
    # changed or new in every repo, plus dotfiles not synced from ~.
    # Unpushed commits and "behind" colour the logo but are not counted.
    changes = sum(r["changed"] + r["untracked"] + r.get("drift", 0) for r in repos)
    return {"text": f"{ICON} {changes}" if changes else ICON, "tooltip": tooltip,
            "class": "unpushed" if unpushed else "dirty"}


def main():
    cmd, args = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ("", [])
    if cmd == "scan":
        print(json.dumps(scan()))
    elif cmd == "fetch":
        print(json.dumps(fetch()))
    elif cmd == "pull" and len(args) == 1:
        ok, text = pull(args[0])
        print(text)
        sys.exit(0 if ok else 1)
    elif cmd == "commit" and len(args) == 1:
        commit(args[0])
    elif cmd == "site" and len(args) == 1:
        url = website(args[0])
        if url:
            print(url)
        sys.exit(0 if url else 1)
    elif cmd == "preview" and len(args) == 1:
        ok, text = preview(args[0])
        print(text)
        sys.exit(0 if ok else 1)
    elif cmd == "preview-stop" and len(args) == 1:
        preview_stop(args[0])
    elif cmd == "serve" and len(args) == 2:
        serve(args[0], int(args[1]))
    else:
        print(json.dumps(bar()))


if __name__ == "__main__":
    main()
