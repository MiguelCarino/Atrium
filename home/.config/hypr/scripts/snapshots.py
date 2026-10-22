#!/usr/bin/env python3
"""System snapshots (snapper, set up by setup-root.sh): see them, take one,
undo an update.

    snapshots.py list [--json]       newest first: updates as pre/post pairs,
                                     then timeline and manual snapshots
    snapshots.py create [text]       a snapshot now ("before I try X")
    snapshots.py undo <pre> <post>   undo what changed between two snapshots
                                     -- an update -- in a terminal, after
                                     showing how many files it touches and
                                     asking (pkexec: your password)
    snapshots.py status              one line: how many, the newest one's age

Snapshots cover / only: /home is its own subvolume, so undoing an update
never touches your files. `undo` is snapper undochange: the files the
update changed go back to how they were before it, in place, while the
system runs -- afterwards reboot if the update touched the kernel, drivers or
the desktop itself.
"""
import datetime
import json
import os
import shlex
import subprocess
import sys

CONFIG = "root"
TERMINAL = ["kitty", "--class", "snapshots-undo", "--title", "Undo update", "-e"]


def snapper(*args, timeout=30):
    return subprocess.run(["snapper", "-c", CONFIG, *args], capture_output=True, text=True, timeout=timeout)


def available():
    try:
        return snapper("list").returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def snapshots():
    """[{number, type, pre, date, description, cleanup}], snapshot 0 left out."""
    out = snapper("--jsonout", "list", "--columns", "number,type,pre-number,date,description,cleanup")
    try:
        rows = json.loads(out.stdout)[CONFIG]
    except (ValueError, KeyError):
        return []
    found = []
    for r in rows:
        if r.get("number") in (0, None):
            continue
        found.append({"number": r["number"], "type": r.get("type", "single"), "pre": r.get("pre-number"),
                      "date": r.get("date", ""), "description": r.get("description", ""),
                      "cleanup": r.get("cleanup", "")})
    return found


def entries():
    """Pairs folded together: [{kind: update|single, pre, post, date, text}],
    newest first."""
    rows = snapshots()
    posts = {r["pre"]: r for r in rows if r["type"] == "post"}
    out = []
    for r in rows:
        if r["type"] == "pre":
            post = posts.get(r["number"])
            out.append({"kind": "update", "pre": r["number"], "post": post["number"] if post else None,
                        "date": (post or r)["date"], "text": short(r["description"])})
        elif r["type"] == "single":
            out.append({"kind": r["cleanup"] or "manual", "pre": r["number"], "post": None,
                        "date": r["date"], "text": short(r["description"]) or r["cleanup"]})
    return sorted(out, key=lambda e: e["date"], reverse=True)


def short(text):
    """"/usr/bin/python3 /usr/bin/dnf upgrade --refresh" -> "dnf upgrade --refresh"."""
    words = text.split()
    for i, w in enumerate(words):
        if os.path.basename(w) in ("dnf", "dnf5"):
            return " ".join(["dnf"] + words[i + 1:])
    return text


def age(date):
    try:
        then = datetime.datetime.fromisoformat(date)
    except ValueError:
        return ""
    mins = int((datetime.datetime.now() - then).total_seconds() // 60)
    if mins < 60:
        return f"{mins} min ago"
    if mins < 48 * 60:
        return f"{mins // 60} h ago"
    return f"{mins // 1440} days ago"


def cmd_undo(pre, post):
    """Runs in a terminal: show the size of the change, ask, undo."""
    script = f"""
set -u
echo "Files changed between snapshot {pre} and {post}:"
snapper -c {CONFIG} status {pre}..{post} | awk '{{print $1}}' | cut -c1 | sort | uniq -c |
    sed 's/ +$/ created (will be deleted)/; s/ -$/ deleted (will be restored)/; s/ c$/ modified (will be put back)/'
echo
read -r -p "Undo these changes to the system? [y/N] " ans
[[ $ans == y ]] || exit 0
pkexec snapper -c {CONFIG} undochange {pre}..{post} && echo && echo "Done. Reboot if the update touched the kernel, drivers or the desktop."
read -r -p "Enter to close"
"""
    subprocess.Popen(TERMINAL + ["bash", "-c", script], start_new_session=True)


def main(argv):
    cmd = argv[0] if argv else "list"
    if not available() and cmd != "status":
        sys.exit("snapper is not set up: sudo ~/.config/hypr/scripts/setup-root.sh")
    if cmd == "list":
        rows = entries()
        if "--json" in argv:
            print(json.dumps(rows))
        for e in [] if "--json" in argv else rows:
            span = f"{e['pre']}..{e['post']}" if e["post"] else str(e["pre"])
            print(f"{span:>9}  {e['kind']:8}  {age(e['date']):>12}  {e['text']}")
    elif cmd == "create":
        text = " ".join(argv[1:]) or "by hand"
        out = snapper("create", "-c", "number", "-p", "-d", text)
        print(f"snapshot {out.stdout.strip()}" if out.returncode == 0 else out.stderr.strip())
    elif cmd == "undo" and len(argv) == 3 and argv[1].isdigit() and argv[2].isdigit():
        cmd_undo(int(argv[1]), int(argv[2]))
    elif cmd == "status":
        if not available():
            print("not set up")
            return
        rows = entries()
        print(f"{len(rows)} snapshots, newest {age(rows[0]['date']) if rows else 'none'}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
