#!/usr/bin/env python3
"""The bar's signal numbers, in one place: which SIGRTMIN+N redraws which pill.

    bar_signals.py list            the table: number, bar, modules, who sends it
    bar_signals.py number NAME...  the numbers alone, one line each (for a
                                   shell script: one fork for several)
    bar_signals.py poke NAME...    redraw those pills now (what `pkill
                                   -RTMIN+N -x waybar` did, without the fork)
    bar_signals.py free            the numbers nobody uses yet

A custom module in ~/.config/waybar/config (or config-toolbox) with
"signal": N re-runs its exec when its waybar gets SIGRTMIN+N. The numbers
used to live in a dozen scripts as bare literals ("SIGNAL = 19  # custom/
drives") and in the config, and nothing checked that they agreed. This is
the table now: Python scripts import it (signal_number / poke), shell
scripts call `bar_signals.py poke NAME`, and tests/test_bar_signals.py fails
when a "signal" in the waybar configs is not the number listed here for that
module, or two names claim one number for different modules.

poke() only signals a waybar that has its handler for that signal installed
(SigCgt in /proc/<pid>/status): the default action of a real-time signal is
to terminate, so a waybar still starting up -- the toolbox is restarted each
time its card is refit -- must not be hit. pkill had no such check.

The "bar" column: "main" is the top bar (config), "toolbox" the drop-down
card (config-toolbox, waybar-toolbox.service); poke() signals only that
waybar, so the other never re-runs scripts for nothing.

HYPR_BAR_SIGNALS_OFF=1 in the environment turns poke() into a no-op (it
still returns 0): the tests set it, so a script under test that redraws a
pill never reaches the live bar. A kill= passed in (the tests' fake) is
used regardless.

Choosing a new number: take one from `bar_signals.py free` (waybar accepts
1..30 here, SIGRTMIN+30 = SIGRTMAX on Linux), add it to SIGNALS with every
module that uses it, then use it in the config.
"""
import os
import signal
import sys

# name -> (number, bar, modules that carry it, who sends it). Several names
# may share a number only when they are the same modules (aliases).
SIGNALS = {
    # updates also carries the restart badge (updates.sh asks reboot_needed.py
    # on every run), so whatever learns a restart is or is not due any more
    # pokes it: reboot_panel.py's Check again (the updates card's RESTART
    # section) and safe-upgrade.sh. The old reboot pill's 28 is free again.
    "updates":       (8,  "main",    ("custom/updates",),
                      "updates.sh / updates_panel.py / reboot_panel.py (Check again) / safe-upgrade.sh"
                      " / software-updates.py / theme.py"),
    "day":           (10, "main",    ("custom/day", "custom/logo", "custom/menuclock", "custom/power"),
                      "theme.py (bar.conf), region.py, clock.py (date change)"),
    "nightlight":    (11, "toolbox", ("custom/nightlight",), "nightlight.sh (on a real change)"),
    "toolbox":       (12, "main",    ("custom/toolbox",), "toolbox.sh (open / close)"),
    "display":       (13, "toolbox", ("custom/display",), "display.py, theme.py"),
    "notifications": (14, "main",    ("custom/notifications",),
                      "notifications.py, auto-dnd.py, notify-settings.py, timers.py"),
    "repos":         (15, "main",    ("custom/repos",),
                      "repos.py, repos_panel.py, dotfiles.py, dotfiles-backup.sh"),
    "weather":       (16, "main",    ("custom/weather",), "theme.py, region.py, wttr.py (back online)"),
    "workhours":     (17, "main",    ("custom/workhours",), "workhours.py"),
    "doctor":        (18, "main",    ("custom/doctor",), "doctor.py --fix (the pill), launcher.py"),
    "drives":        (19, "main",    ("custom/drives",), "automount.py daemon"),
    "phone":         (20, "main",    ("custom/phone",), "phone.py watch (connect / battery)"),
    "awake":         (21, "toolbox", ("custom/awake",), "toolbox_awake.py, toolbox.sh (card opens), idle-settings.py (keep-awake starts / ends)"),
    "printing":      (22, "main",    ("custom/printing",), "printing.py watch"),
    "context":       (24, "main",    ("custom/context",), "contexts.py"),
    "tasks":         (27, "main",    ("custom/tasks",), "tasks.py"),
}
# Aliases: the same number under the name a reader looks for.
SIGNALS["logo"] = SIGNALS["menuclock"] = SIGNALS["power"] = SIGNALS["day"]

LOWEST, HIGHEST = 1, 30
TOOLBOX_CONFIG = "config-toolbox"


def signal_number(name):
    """SIGRTMIN offset for NAME (KeyError for an unknown name: a typo here
    should fail loudly in a test, not silently redraw nothing)."""
    return SIGNALS[name][0]


def free_numbers():
    used = {entry[0] for entry in SIGNALS.values()}
    return [n for n in range(LOWEST, HIGHEST + 1) if n not in used]


def _read(path):
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError:
        return b""


def catches(status_text, signum):
    """Does a /proc/<pid>/status text say this process handles signum?"""
    for line in status_text.splitlines():
        if line.startswith("SigCgt:"):
            try:
                return bool((int(line.split()[1], 16) >> (signum - 1)) & 1)
            except (IndexError, ValueError):
                return False
    return False


def waybars(proc="/proc"):
    """[(pid, bar)] of the running waybars; bar is "main" or "toolbox"."""
    found = []
    try:
        pids = [p for p in os.listdir(proc) if p.isdigit()]
    except OSError:
        return found
    for pid in pids:
        if _read(f"{proc}/{pid}/comm").strip() != b"waybar":
            continue
        cmdline = _read(f"{proc}/{pid}/cmdline").decode(errors="replace")
        found.append((int(pid), "toolbox" if TOOLBOX_CONFIG in cmdline else "main"))
    return found


def poke(*names, proc="/proc", kill=os.kill):
    """Send each named pill's signal to the waybar that has it. Returns the
    number of signals sent. Never raises: a bar that is not running is
    simply nothing to redraw."""
    sent = 0
    if kill is os.kill and os.environ.get("HYPR_BAR_SIGNALS_OFF") == "1":
        return sent
    bars = waybars(proc)
    for name in names:
        number, bar = SIGNALS[name][:2]
        signum = signal.SIGRTMIN + number
        for pid, which in bars:
            if which != bar:
                continue
            if not catches(_read(f"{proc}/{pid}/status").decode(errors="replace"), signum):
                continue
            try:
                kill(pid, signum)
                sent += 1
            except OSError:
                pass
    return sent


def main(argv):
    cmd = argv[0] if argv else "list"
    if cmd == "list":
        seen = set()
        for name, (number, bar, modules, who) in sorted(SIGNALS.items(), key=lambda kv: kv[1][0]):
            if number in seen:
                continue
            seen.add(number)
            print(f"{number:>3}  {bar:<8} {name:<14} {', '.join(modules)}\n{'':>14}sent by: {who}")
        print(f"free: {' '.join(map(str, free_numbers()))}")
    elif cmd == "number" and argv[1:] and all(n in SIGNALS for n in argv[1:]):
        print("\n".join(str(signal_number(n)) for n in argv[1:]))
    elif cmd == "poke" and argv[1:] and all(n in SIGNALS for n in argv[1:]):
        poke(*argv[1:])
    elif cmd == "free":
        print(" ".join(map(str, free_numbers())))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
