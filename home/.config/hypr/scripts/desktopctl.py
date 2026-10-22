#!/usr/bin/env python3
"""Everything the display panel shows, read in ONE process.

    desktopctl.py status     one JSON object:
        display    display.py status (outputs, HDR, rates, filter, theme...)
        screens    screen-color.py status (brightness / colour per screen)
        schedule   theme-schedule.py status --json
        glass      theme.py glass (the current theme's window glass)
        fade       "on" | "off"   (theme.py fade)
        sounds     "on" | "off"   (theme-sound.sh)
        motion     {"video", "on"} (wallpaper-slideshow.py motion)
        react      "on" | "off"   (wallpaper-motion.py react)

Why: the panel used to start eight scripts for every redraw -- each its own
Python, each importing theme.py again -- about 0.6 s per click. Here the
same modules are imported once and their status functions called directly,
so a redraw is one process. Changing something still goes through each
script's own command (the panel, launcher and keys all do), so there is
still exactly one place that applies each setting.
"""
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def load(name):
    """A script by file name (several have dashes) as a module."""
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), os.path.join(HERE, name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def status():
    import display
    import theme
    state = theme.read_state()
    out = {}
    for key, fn in (("display", display.status_data),
                    ("screens", lambda: load("screen-color").status_data()),
                    ("schedule", lambda: load("theme-schedule").status_data()),
                    ("glass", lambda: theme.glass_info(theme.load())),
                    ("motion", lambda: (lambda m: {"video": m.video_name(), "on": m.motion_on()})(
                        load("wallpaper-slideshow")))):
        try:
            out[key] = fn()
        except Exception as exc:        # one broken part must not blank the panel
            out[key] = {"error": f"{type(exc).__name__}: {exc}"}
    out["fade"] = "off" if state.get("fade") == "off" else "on"
    out["sounds"] = "off" if state.get("sounds") == "off" else "on"
    out["react"] = "off" if state.get("wallpaper_react") == "off" else "on"
    return out


def main(argv):
    if (argv or ["status"])[0] == "status":
        print(json.dumps(status()))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
