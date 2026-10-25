#!/usr/bin/env python3
"""Picture-in-picture for a playing mpv: the mpv window ITSELF goes small,
floating and pinned into a screen corner, and back again.

    mpv-pip.py toggle PID [W H]   into the corner, or back where it was
    mpv-pip.py on PID [W H]       into the corner (already there: nothing)
    mpv-pip.py off PID            back (not in the corner: nothing)
    mpv-pip.py status PID

Each prints the window's state afterwards, "on" or "off", for the caller:
~/.config/mpv/scripts/window-pip.lua, behind the picture-in-picture button
in mpv's controls row (themes/mpv-base.conf) and in the Liquid Glass skin.
PID is mpv's own pid -- that is how the window is found in `hyprctl
clients`, the way scripts/maximize-first.lua finds it. W H are the video's
display size (mpv's dwidth / dheight), so the small window has the
picture's shape and no black bars; without them the window's current shape
is used.

WHY NOT scripts/pip.py. That one makes a live COPY of a window (grim
frames into a second mpv, ~10 fps for a window, no sound, no controls),
which is right for mirroring a browser or a call you cannot move. A video
player can simply be moved: the real window keeps its full frame rate, HDR,
sound and its own controls, and costs nothing extra. What is shared with
pip.py is the user's choice of where and how big -- Settings'
picture-in-picture `width` and `corner` (~/.local/state/hypr/pip.conf) --
and its corner arithmetic (pip.fit / pip.place), so the mirror and the
moved player land in the same place.

What "on" does, in one `hyprctl eval` (this desktop's config is Lua, so a
plain `hyprctl dispatch pin` is a syntax error -- see waybar/scripts/
fsstate.py): leave Hyprland's maximized state if maximize-first.lua put the
window there, float it, size it to `width` on its long side, park it in
`corner` of the screen it is on, pin it (so it is on every workspace of
that screen and stays above the tiles). mpv's OWN fullscreen is left by
window-pip.lua before it calls this, so mpv knows it is no longer
fullscreen. The window's state before is kept in $XDG_RUNTIME_DIR/
mpv-pip.json, by window address, and "off" puts back exactly that: the same
floating size and place, or tiled again, and maximized again if it was (a
record whose size and place are not four numbers -- a hand edit -- counts as
none and the window is tiled: checked_record()).
A pinned window comes back on the workspace you are on now -- it followed
you there.

ALT+left-drag still moves it and ALT+right-drag resizes it while it is
small; SUPER+SHIFT+P on it also puts it back (unpin + tile, binds.lua).
"""
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _load_pip():
    """scripts/pip.py, by path: the shared settings and corner geometry.
    Not `import pip`, which could just as well find Python's package
    installer of the same name."""
    spec = importlib.util.spec_from_file_location("desktop_pip", os.path.join(HERE, "pip.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pip = _load_pip()

RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
RECORDS = os.path.join(RUNTIME, "mpv-pip.json")

# Hyprland's internal fullscreen modes in `hyprctl clients -j`.
MAXIMIZED, FULLSCREEN = 1, 2


# -- the window (pure) -------------------------------------------------------------------
def find_client(clients, pid):
    """mpv's window among `hyprctl clients -j`: the mapped one with that pid."""
    for c in clients or []:
        if c.get("pid") == pid and c.get("mapped", True):
            return c
    return None


def is_on(client):
    """In the corner = floating and pinned. That is also what SUPER+SHIFT+P
    leaves behind, so one made by hand counts too (and "off" tiles it)."""
    return bool(client.get("floating") and client.get("pinned"))


def monitor_of(client, monitors):
    mons = monitors or []
    return next((m for m in mons if m.get("id") == client.get("monitor")),
                next((m for m in mons if m.get("focused")), mons[0] if mons else None))


def target(client):
    return f'"address:{client["address"]}"'


def enter_calls(client, mon, settings, video=None):
    """(the Lua dispatches, the record to keep) to put CLIENT in the corner."""
    t = target(client)
    width = int(settings["width"])
    src_w, src_h = video if video and video[0] > 0 and video[1] > 0 else client["size"]
    size = pip.fit(src_w, src_h, width)
    x, y = pip.place(mon, size, settings["corner"])
    calls = []
    fs = client.get("fullscreen", 0)
    if fs:
        mode = "maximized" if fs == MAXIMIZED else "fullscreen"
        calls.append(f'hl.dsp.window.fullscreen({{ mode = "{mode}", action = "unset", window = {t} }})')
    if not client.get("floating"):
        calls.append(f'hl.dsp.window.float({{ action = "enable", window = {t} }})')
    calls.append(f"hl.dsp.window.resize({{ x = {size[0]}, y = {size[1]}, window = {t} }})")
    calls.append(f"hl.dsp.window.move({{ x = {x}, y = {y}, window = {t} }})")
    if not client.get("pinned"):
        calls.append(f"hl.dsp.window.pin({{ window = {t} }})")
    record = {"floating": bool(client.get("floating")), "at": list(client["at"]),
              "size": list(client["size"]), "fullscreen": fs}
    return calls, record


def checked_record(record):
    """RECORD with its size and place as four ints, or None when it is not
    one enter_calls() could have written. The file is read back from
    $XDG_RUNTIME_DIR, and its numbers go into Lua text for `hyprctl eval`:
    a hand-edited string there would run inside the compositor, and a
    wrong shape (a 3-item list, null) raised in the unpacking and left the
    window stuck in the corner. Not valid: tiled back, as with no record."""
    if not isinstance(record, dict):
        return None
    try:
        (w, h), (x, y) = record["size"], record["at"]
        size, at = [int(w), int(h)], [int(x), int(y)]
    except (KeyError, TypeError, ValueError):
        return None
    return dict(record, size=size, at=at)


def leave_calls(client, record):
    """The Lua dispatches to put CLIENT back as RECORD says it was (no
    record, or one that does not read: tiled, the way SUPER+SHIFT+P puts a
    window back)."""
    t = target(client)
    record = checked_record(record)
    calls = []
    if client.get("pinned"):
        calls.append(f"hl.dsp.window.pin({{ window = {t} }})")
    if record and record.get("floating"):
        (w, h), (x, y) = record["size"], record["at"]
        calls.append(f"hl.dsp.window.resize({{ x = {w}, y = {h}, window = {t} }})")
        calls.append(f"hl.dsp.window.move({{ x = {x}, y = {y}, window = {t} }})")
    elif client.get("floating"):
        calls.append(f'hl.dsp.window.float({{ action = "disable", window = {t} }})')
    if record and record.get("fullscreen") == MAXIMIZED:
        calls.append(f'hl.dsp.window.fullscreen({{ mode = "maximized", action = "set", window = {t} }})')
    return calls


def lua(calls):
    """One `hyprctl eval` chunk: every dispatch in order, in one round trip."""
    return "; ".join(f"hl.dispatch({c})" for c in calls)


# -- the records -------------------------------------------------------------------------
def load_records(path=None):
    try:
        with open(path or RECORDS) as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_records(records, clients, path=None):
    """Write RECORDS, dropping any whose window is gone (a closed mpv's)."""
    path = path or RECORDS
    alive = {c.get("address") for c in clients or []}
    records = {a: r for a, r in records.items() if a in alive}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w") as handle:
        json.dump(records, handle)
    os.replace(path + ".tmp", path)


# -- main --------------------------------------------------------------------------------
def run(cmd, pid, video=None, hypr_json=pip.hypr_json, hypr_eval=pip.hypr_eval):
    """Do CMD for mpv PID; returns "on" / "off", or None when there is no
    such window (not under Hyprland, or mpv has no window yet)."""
    clients = hypr_json("clients")
    client = find_client(clients, pid)
    if client is None:
        return None
    on = is_on(client)
    want = (not on) if cmd == "toggle" else {"on": True, "off": False}.get(cmd, on)
    if want == on:
        return "on" if on else "off"
    records = load_records()
    address = client["address"]
    if want:
        calls, record = enter_calls(client, monitor_of(client, hypr_json("monitors")),
                                    pip.read_settings(), video)
        records[address] = record
    else:
        calls = leave_calls(client, records.pop(address, None))
    hypr_eval(lua(calls))
    save_records(records, clients)
    return "on" if want else "off"


def main(argv):
    if len(argv) < 2 or argv[0] not in ("toggle", "on", "off", "status"):
        sys.exit(__doc__)
    try:
        pid = int(argv[1])
        video = (int(float(argv[2])), int(float(argv[3]))) if len(argv) >= 4 else None
    except ValueError:
        sys.exit(__doc__)
    state = run(argv[0], pid, video)
    if state is None:
        print("off")
        sys.exit("mpv-pip: no Hyprland window for that pid")
    print(state)


if __name__ == "__main__":
    main(sys.argv[1:])
