#!/usr/bin/env python3
"""One way for desktop scripts to log: into the user journal, tagged, so a
script started from a key bind (not a service) lands in the same place as
the services do -- `journalctl --user -t <tag>`, the logs panel, doctor.py.

    import desklog
    desklog.log("theme", "switched to aero")
    desklog.log("theme", "gtk.css missing", "error")

    desklog.py <tag> <level> <message...>      the same from a shell script

level: debug, info, notice, warning, error, critical. Uses python3-systemd's
journal.send when it is installed, else `logger -t` (util-linux), and never
raises: logging must not be what breaks a script.
"""
import subprocess
import sys

LEVELS = {"debug": 7, "info": 6, "notice": 5, "warning": 4, "error": 3, "critical": 2}

try:
    from systemd import journal as _journal
except ImportError:         # pragma: no cover - depends on the machine
    _journal = None


def log(tag, msg, level="info"):
    prio = LEVELS.get(level, 6)
    try:
        if _journal is not None:
            _journal.send(str(msg), SYSLOG_IDENTIFIER=tag, PRIORITY=prio)
        else:
            subprocess.run(["logger", "-t", tag, "-p", f"user.{level if level in LEVELS else 'info'}",
                            str(msg)], timeout=3, check=False)
    except Exception:       # noqa: BLE001 - see the docstring
        pass


if __name__ == "__main__":
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    log(sys.argv[1], " ".join(sys.argv[3:]), sys.argv[2])
