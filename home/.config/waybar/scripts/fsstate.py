#!/usr/bin/env python3
"""Split fullscreen state toggle for waybar.

Hyprland tracks two fullscreen states per window and normally moves them
together:

    internal  what Hyprland actually does with the window's geometry
    client    what the application is *told* over the protocol

Decoupling them is the whole point of this module. Two combinations are
useful for games, and they are opposites:

    A  internal=0 client=2   the game believes it is fullscreen and uses its
                             fullscreen render path, but stays an ordinary
                             tiled window you can see other things beside
    B  internal=2 client=0   the window fills the monitor while the game
                             believes it is windowed -- "borderless windowed",
                             which avoids a video mode switch and the alt-tab
                             stutter that comes with exclusive fullscreen

    fsstate.py status     one-shot JSON for a custom module
    fsstate.py watch      JSON on every change, forever, for a module with
                          no "interval"
    fsstate.py a          toggle mode A on the focused window
    fsstate.py b          toggle mode B on the focused window
    fsstate.py reset      return the focused window to plain windowed (0,0)

Icons are Font Awesome 6 codepoints written as escapes, matching the rest of
the bar: no Nerd Font is installed on this machine, and literal Private-Use
characters do not survive being copied around.

IMPORTANT -- dispatch syntax. This machine's Hyprland config is Lua
(hyprland.lua), which makes `hyprctl dispatch` evaluate its argument as Lua
rather than hyprlang. The classic `hyprctl dispatch fullscreenstate 0 2` form
is a syntax error here, exactly like the dpms trap documented in
hypridle.conf. Everything below uses the hl.dsp.* form.
"""

import json
import os
import select
import socket
import subprocess
import sys

sys.path.insert(0, os.path.expanduser("~/.config/hypr/scripts"))
import desk_common  # noqa: E402  (hypr/scripts/desk_common.py: hyprctl over the socket)

ICON = "\uf11b"  # gamepad

# (internal, client) pairs. Named so the comparisons below read as intent
# rather than as coordinates.
OFF    = (0, 0)
MODE_A = (0, 2)
MODE_B = (2, 0)

LABELS = {
    OFF:    "off",
    MODE_A: "A",
    MODE_B: "B",
}

# CSS classes, kept separate from LABELS because the bar's stylesheet wants
# kebab-case selectors and the tooltip wants something a human reads.
CLASSES = {
    OFF:    "idle",
    MODE_A: "mode-a",
    MODE_B: "mode-b",
}

# How long watch mode waits on the event socket before re-reading state
# anyway. Events alone are not enough: Hyprland emits `fullscreen` when the
# *internal* state changes, and mode A never changes it -- the window stays
# windowed and only the client is told otherwise. Without this fallback the
# bar would sit stale on exactly the mode this module exists to provide.
# Was 1.5 s with a hyprctl process each time; with the socket request below
# a read costs no process at all (desk_common.hypr_request), and 3 s is still
# prompt for a toggle.
POLL_SECONDS = 3.0


def run(cmd, timeout=3):
    """Run a command and return stdout, or None if it fails in any way."""
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=timeout,
                             text=True, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout


def active_window():
    """The focused window as a dict, or None if there isn't one.

    Clicking a waybar pill does not move Hyprland's focus -- the bar is a
    layer surface with no keyboard interactivity, so pointer events on it
    leave the focused toplevel alone. That is what makes "act on the focused
    window" the right target for a button in the bar rather than a trap.

    One call, not one per field: watch() runs this every POLL_SECONDS, and
    splitting state and title into separate helpers would double the number
    of processes spawned for the whole session's idle cost.
    """
    win = desk_common.hypr_request("activewindow", json=True, timeout=2)
    # Hyprland reports an empty object when nothing is focused.
    if not win or "address" not in win:
        return None
    return win


def state_of(win):
    return (int(win.get("fullscreen", 0)), int(win.get("fullscreenClient", 0)))


def set_state(internal, client):
    """Set both halves explicitly.

    The dispatcher also accepts action="toggle", but this deliberately does
    not use it: toggling with one target while a *different* target is active
    has semantics that are easy to get subtly wrong, and the script already
    knows the current state. Reading it and setting the result outright keeps
    all three buttons predictable -- pressing B while A is on lands on B, not
    on whatever a toggle would have decided.
    """
    expr = ("hl.dsp.window.fullscreen_state({internal=%d, client=%d})"
            % (internal, client))
    run(["hyprctl", "dispatch", expr])


def toggle(target):
    """Turn `target` on, or back off if it is already the current state."""
    win = active_window()
    if win is None:
        return
    current = state_of(win)
    set_state(*(OFF if current == target else target))


def payload():
    win = active_window()

    if win is None:
        return {
            "text": ICON,
            "tooltip": "<b>Fullscreen state</b>\nNo focused window.",
            "class": "none",
            "alt": "none",
        }

    state = state_of(win)

    if state == MODE_A:
        text = f"{ICON} A"
        note = ("<b>Mode A active</b>\n"
                "The app is told it is fullscreen.\n"
                "Hyprland keeps it an ordinary window.")
    elif state == MODE_B:
        text = f"{ICON} B"
        note = ("<b>Mode B active</b>\n"
                "The window fills the monitor.\n"
                "The app is told it is windowed.")
    else:
        text = ICON
        # Anything that is not one of our two pairs is reported honestly
        # rather than as "off" -- a window the user fullscreened normally is
        # (2,2), and calling that "off" would be a lie the tooltip has to
        # answer for the first time someone checks.
        if state == OFF:
            note = "<b>Fullscreen state</b>\nNormal windowed."
        else:
            note = (f"<b>Fullscreen state</b>\n"
                    f"internal={state[0]}, client={state[1]} "
                    f"(not a split mode).")

    title = win.get("title", "") or ""
    if title:
        if len(title) > 60:
            title = title[:59] + "…"
        note += f"\n\n<i>{escape(title)}</i>"

    # No click hints: custom/fsstate has "tooltip": false (they are in the
    # config's comment).

    return {
        "text": text,
        "tooltip": note,
        "class": CLASSES.get(state, "other"),
        "alt": LABELS.get(state, "other"),
    }


def escape(text):
    """Tooltips are pango markup, so a title containing & or < would break it."""
    return (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;"))


def emit():
    """A watcher has to outlive its own errors: an exception raised here would
    end the module for the rest of the session, not just for one sample."""
    try:
        data = payload()
    except Exception as exc:  # noqa: BLE001 - deliberately broad, see above
        data = {"text": ICON, "tooltip": f"fsstate.py: {exc}", "class": "error"}
    print(json.dumps(data), flush=True)
    return data


def event_socket():
    """Hyprland's event stream, or None if it cannot be reached.

    Returning None is not fatal -- watch() falls back to pure polling, which
    is a slower bar but still a correct one.
    """
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if not sig or not runtime:
        return None
    path = os.path.join(runtime, "hypr", sig, ".socket2.sock")
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(path)
    except OSError:
        return None
    return sock


def watch():
    sock = event_socket()
    last = emit()

    while True:
        if sock is not None:
            try:
                ready, _, _ = select.select([sock], [], [], POLL_SECONDS)
            except OSError:
                ready = []
            if ready:
                try:
                    chunk = sock.recv(8192)
                except OSError:
                    chunk = b""
                if not chunk:
                    # Compositor went away or the stream broke. Drop to
                    # polling rather than spinning on a dead socket.
                    sock.close()
                    sock = None
                # The specific event does not matter: every one of them is a
                # reason to re-read state, and re-reading is one cheap call.
        else:
            try:
                select.select([], [], [], POLL_SECONDS)
            except OSError:
                pass

        try:
            data = payload()
        except Exception as exc:  # noqa: BLE001
            data = {"text": ICON, "tooltip": f"fsstate.py: {exc}",
                    "class": "error"}
        # Only speak when something actually changed. waybar tolerates
        # repeats, but a quiet stream makes `fsstate.py watch` readable by
        # hand when something looks wrong.
        if data != last:
            print(json.dumps(data), flush=True)
            last = data


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "status"

    if action == "status":
        emit()
    elif action == "watch":
        watch()
    elif action == "a":
        toggle(MODE_A)
    elif action == "b":
        toggle(MODE_B)
    elif action == "reset":
        set_state(*OFF)
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
