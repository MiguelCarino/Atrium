#!/usr/bin/env python3
"""Dotfiles drift: whether the live config in $HOME and the dotfiles repo
still match. Shown as the dotfiles row of the git panel (repos.py adds the
count to its scan) and in the colour of the git logo; no pill of its own.

    dotfiles.py          the drift report, one line of JSON
    dotfiles.py sync     what the panel's Sync runs in a terminal: copy home ->
                         repo and show the diff stat, then ask before
                         committing and pushing

Which repo: dotfiles= in ~/.config/hypr/desktop.conf (hypr/scripts/
desktop_conf.py), and only when it has a sync.sh. None set: no dotfiles row,
no drift, and `sync` says so -- the git pill is just about your repos.

The repo is a copy, not a symlink farm: its sync.sh rsyncs the paths it
lists from $HOME into home/. So an edit to ~/.config is invisible to
the repo until the next sync -- easy to forget, and the reason this exists.
The numbers come from `sync.sh --check`, a dry-run rsync (nothing is copied):

    drift        files in $HOME that differ from the repo's copy
    uncommitted  files changed in the repo itself and not committed
    unpushed     commits not on GitHub yet

"""

import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.expanduser("~/.config/hypr/scripts"))
import desktop_conf  # noqa: E402  (desktop.conf: dotfiles=)

REPO = desktop_conf.dotfiles_repo()             # None: no dotfiles repo set
SYNC = os.path.join(REPO, "sync.sh") if REPO else None
SIGNAL = 15             # the git pill (custom/repos)


def check():
    if not SYNC:
        return None
    try:
        out = subprocess.run(["nice", "-n", "19", SYNC, "--check"], capture_output=True,
                             text=True, timeout=60).stdout
        return json.loads(out)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def sync():
    """Interactive, in a terminal. Committing is always a question, never a
    side effect of clicking the pill."""
    if not REPO:
        input("No dotfiles repo set (dotfiles= in ~/.config/hypr/desktop.conf). Press Enter to close. ")
        return
    os.chdir(REPO)
    subprocess.run([SYNC])
    try:
        answer = input("\nCommit and push these? [y/N] ").strip().lower()
    except EOFError:
        answer = ""
    if answer == "y":
        subprocess.run([SYNC, "--commit"])
    subprocess.run(["pkill", f"-RTMIN+{SIGNAL}", "-x", "waybar"])
    input("\nDone -- press Enter to close. ")


def main():
    if sys.argv[1:2] == ["sync"]:
        sync()
    else:
        print(json.dumps(check()))


if __name__ == "__main__":
    main()
