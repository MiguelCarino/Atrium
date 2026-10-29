#!/usr/bin/env python3
"""Fire-and-forget events for the dynamic island (island.py). Railguard's
alerts and the desktop's own notifications (scripts/notify) are pushed
here; the island shows a short line of them at the top of the screen.
Mako still shows every notification: this is only a copy -- and with
island.py's "notifications" on (every notification in the island, read off
the bus) the island drops the "notify" copies, so none shows twice;
Railguard's alert and its notification become one card there.

One JSON datagram to $XDG_RUNTIME_DIR/island.sock, at most 8000 bytes,
every string cut to LIMIT characters:

    {"v":1,"src":"notify","summary":..,"body":..,"app":..,"urgency":..}
    {"v":1,"src":"railguard","title":..,"body":..,"mood":"calm|alert|relieved"}

Stdlib only, never raises, never blocks: with the island off there is no
socket and send() returns False at once; a stale socket with nobody
listening is a refused send, swallowed the same way.

    send(msg) -> bool                       True when it went out
    notify(summary, body="", app=None, urgency=None) -> bool
    railguard(title, body="", mood="alert") -> bool
"""
import json
import os
import socket

RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
SOCK = os.path.join(RUNTIME, "island.sock")
LIMIT = 300


def cut(text):
    return str(text)[:LIMIT]


def send(msg):
    """One datagram to the island (v=1 added); False when it is not there."""
    if not os.path.exists(SOCK):
        return False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
            s.setblocking(False)
            s.sendto(json.dumps(dict(msg, v=1)).encode()[:8000], SOCK)
        return True
    except Exception:
        return False


def notify(summary, body="", app=None, urgency=None):
    """A desktop notification's summary line (mascot_notify's hook)."""
    return send({"src": "notify", "summary": cut(summary), "body": cut(body or ""),
                 "app": cut(app or ""), "urgency": cut(urgency or "normal")})


def railguard(title, body="", mood="alert"):
    """A Railguard alert, with the mood its mascot shows."""
    return send({"src": "railguard", "title": cut(title), "body": cut(body or ""),
                 "mood": cut(mood or "alert")})
