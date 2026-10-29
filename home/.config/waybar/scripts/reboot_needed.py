#!/usr/bin/env python3
"""Is a restart due? -- the updates pill's restart badge: nothing normally;
a circular arrow beside the updates count (custom/updates, updates.sh) when
this machine is running something older than what is installed, so the next
restart is due. It used to be a pill of its own (custom/reboot); a restart
is what an upgrade leaves behind, so it went where the upgrade is.

    reboot_needed.py            the reasons, one sentence a line; nothing
    reboot_needed.py reasons    when no restart is due (what updates.sh reads)
    reboot_needed.py status     the reasons, as JSON (what the card reads)
    reboot_needed.py refresh    ask needs-restarting again now, ignoring
                                the cache

Two reasons, the cheap one first:

  kernel    the running kernel (uname -r) is not the newest one installed:
            /lib/modules/<version> folders that hold a vmlinuz (a folder
            left behind by a removed kernel has none), compared as versions
            (7.2.10 < 7.2.11, not as text).
  packages  `needs-restarting -r` (dnf-utils / dnf5-plugins) says core
            libraries or services were updated since boot -- glibc,
            systemd, linux-firmware and the like. It loads dnf, so it takes
            seconds; its answer is kept in $XDG_RUNTIME_DIR for
            NEEDS_TTL (30 min); updates.sh asks on each of its checks (hourly,
            and whenever bar_signals.py "updates" redraws it), so a stale
            answer is re-asked there, in the pill's background exec, never
            in a card. Without the tool the reason is simply not checked
            (the status says so).

Click on the updates pill: the updates card (updates_panel.py), whose
RESTART section is reboot_panel.py's: why, Check again, and a "Reboot now"
that takes two clicks (panelui.Armed). Nothing here ever reboots by itself.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time

MODULES = "/lib/modules"
CACHE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "reboot-needed.json")
NEEDS_TTL = 1800            # s an answer from needs-restarting is trusted
NEEDS_TIMEOUT = 90          # s; it loads the whole dnf stack


# -- pure ---------------------------------------------------------------------
def version_key(release):
    """A sort key for kernel releases: numbers compare as numbers, so
    "7.2.11-200.fc44.x86_64" > "7.2.9-201.fc44.x86_64"."""
    return [(0, int(part), "") if part.isdigit() else (1, 0, part)
            for part in re.split(r"[.\-_+~]", release)]


def newest_kernel(installed):
    """The newest release in a list, or None for an empty one."""
    return max(installed, key=version_key) if installed else None


def kernel_reason(running, installed):
    """"" when the running kernel is the newest installed one (or nothing is
    known), else a sentence saying which is waiting."""
    newest = newest_kernel(installed)
    if not newest or not running or newest == running:
        return ""
    if version_key(newest) <= version_key(running):
        return ""
    return f"Kernel {newest} is installed; {running} is running."


def parse_needs_restarting(rc, out):
    """needs-restarting -r: exit 1 and a list of packages when a reboot is
    needed, 0 when not. -> (needed, [package names])."""
    if rc != 1:
        return False, []
    pkgs = [m.group(1) for m in re.finditer(r"^\s*\*\s*(\S+)", out or "", re.M)]
    return True, pkgs


def packages_reason(needed, pkgs):
    if not needed:
        return ""
    if not pkgs:
        return "Core libraries or services were updated since boot."
    shown = ", ".join(pkgs[:4]) + (f" and {len(pkgs) - 4} more" if len(pkgs) > 4 else "")
    return f"Updated since boot: {shown}."


def fresh(saved, now, ttl=NEEDS_TTL):
    """Is a cached needs-restarting answer still good?"""
    return bool(saved) and isinstance(saved.get("at"), (int, float)) and 0 <= now - saved["at"] < ttl


def reasons_text(reasons):
    """`reasons` mode's output: one sentence a line, "" with none -- so
    updates.sh only has to ask whether it printed anything."""
    return "\n".join(r.replace("\n", " ") for r in reasons if r)


# -- the machine --------------------------------------------------------------
def installed_kernels(root=MODULES):
    try:
        names = os.listdir(root)
    except OSError:
        return []
    return [n for n in names if os.path.exists(os.path.join(root, n, "vmlinuz"))]


def running_kernel():
    return os.uname().release


def read_cache():
    try:
        with open(CACHE) as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def ask_needs_restarting():
    """(available, needed, pkgs). Not installed: (False, False, [])."""
    tool = shutil.which("needs-restarting")
    if not tool:
        return False, False, []
    try:
        proc = subprocess.run([tool, "-r"], capture_output=True, text=True, timeout=NEEDS_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return True, False, []
    needed, pkgs = parse_needs_restarting(proc.returncode, proc.stdout)
    return True, needed, pkgs


def packages_state(force=False, run=True):
    """The cached needs-restarting answer while fresh, else a new one. With
    run=False never a new one (the panel's first draw must not wait
    seconds): the cache however old, or {} without one."""
    saved = read_cache()
    if not force and (fresh(saved, time.time()) or not run):
        return saved
    available, needed, pkgs = ask_needs_restarting()
    saved = {"at": time.time(), "available": available, "needed": needed, "pkgs": pkgs}
    try:
        with open(CACHE, "w") as handle:
            json.dump(saved, handle)
    except OSError:
        pass
    return saved


def status(force=False, run=True):
    running, installed = running_kernel(), installed_kernels()
    pk = packages_state(force, run)
    reasons = [r for r in (kernel_reason(running, installed),
                           packages_reason(pk.get("needed"), pk.get("pkgs") or [])) if r]
    return {"reasons": reasons, "running": running, "newest": newest_kernel(installed),
            "checker": bool(pk.get("available")), "checked_at": pk.get("at")}


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "reasons"
    if cmd == "status":
        print(json.dumps(status()))
    elif cmd == "refresh":
        print(json.dumps(status(force=True)))
    else:
        text = reasons_text(status()["reasons"])
        if text:
            print(text)


if __name__ == "__main__":
    main()
