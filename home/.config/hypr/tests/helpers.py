"""Shared test setup: a scratch XDG_STATE_HOME / XDG_CACHE_HOME / runtime
dir for the whole run (set before any script is imported, since several
read their paths at import time), and import_script() for the scripts whose
file names have dashes in them.

Nothing here touches the real state, the screens or the services: the
scripts' own subprocess calls are stubbed in each test where a function
would make one."""
import atexit
import importlib.util
import os
import unittest
import shutil
import sys
import tempfile

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")

# The Atrium checkout around these tests (home/.config/hypr/tests -> the repo),
# or None when they run from a live install (~/.config/hypr/tests, as
# sync.sh --commit runs them): the tests of repo-only files (install.sh,
# packages/, system/) are skipped there.
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(SCRIPTS))))
REPO = _REPO if os.path.isfile(os.path.join(_REPO, "install.sh")) else None
needs_repo = unittest.skipUnless(REPO, "not in an Atrium checkout (no install.sh, packages/, system/)")
SCRATCH = tempfile.mkdtemp(prefix="hypr-tests-")
atexit.register(shutil.rmtree, SCRATCH, True)

for var, sub in (("XDG_STATE_HOME", "state"), ("XDG_CACHE_HOME", "cache"), ("XDG_RUNTIME_DIR", "run")):
    os.makedirs(os.path.join(SCRATCH, sub), exist_ok=True)
    os.environ[var] = os.path.join(SCRATCH, sub)
os.environ.pop("HYPRLAND_INSTANCE_SIGNATURE", None)    # a stray hyprctl call fails instead of acting
# bar_signals.poke() is a no-op for the whole run (a fake kill= passed in
# still counts): a script under test that redraws a pill never signals the
# live bar -- nor does any script a test runs as a subprocess (it inherits
# the environment).
os.environ["HYPR_BAR_SIGNALS_OFF"] = "1"
# desktop.conf and workhours.conf: scratch copies, never yours. The projects
# folder is ~/Projects (it need not exist: the tests that list repos give
# their own folder); work hours start OFF (no file), as on a new desktop.
os.makedirs(os.path.join(SCRATCH, "config"), exist_ok=True)
os.environ["HYPR_DESKTOP_CONF"] = os.path.join(SCRATCH, "config", "desktop.conf")
with open(os.environ["HYPR_DESKTOP_CONF"], "w") as _handle:
    _handle.write("projects=~/Projects\n")
os.environ["HYPR_WORKHOURS_CONF"] = os.path.join(SCRATCH, "config", "workhours.conf")
# Folder access (folder_access.py): a scratch store with nothing granted, and
# never a real prompt on the screen -- a request that would ask is a no
# unless the test hands in its own fake prompter.
os.environ["HYPR_FOLDER_ACCESS"] = os.path.join(SCRATCH, "config", "folder-access.json")
os.environ["HYPR_FOLDER_ACCESS_NO_PROMPT"] = "1"
# The screens (scripts/screens.py): a fixed three-screen host file instead of
# this machine's, so primary / order / HDR are the same wherever this runs.
os.environ["HYPR_HOST_FILE"] = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                            "fixtures", "host-three-screens.lua")
# ... and no kernel connectors (screens.drm_screens): a folder that is not
# there, so the fallbacks without Hyprland never read this machine's /sys.
os.environ["HYPR_DRM_DIR"] = os.path.join(SCRATCH, "no-drm")
# ... and no power supplies (power_state.py): a folder that is not there, so
# every script under test sees a desktop PC -- never on battery, nothing to
# back off from -- whether the tests run on a laptop unplugged or not. The
# battery tests build their own fake tree and point ATRIUM_POWER_SUPPLY (or
# a root= argument) at it.
os.environ["ATRIUM_POWER_SUPPLY"] = os.path.join(SCRATCH, "no-power-supply")
# Claude Code: a stand-in `claude` that does nothing (exit 1), so the tests
# of the Claude backend find one whether or not this machine has it, and no
# test can reach the real one. The no-claude tests set HYPR_CLAUDE_CLI=none
# (or run with a PATH and HOME without it).
os.makedirs(os.path.join(SCRATCH, "bin"), exist_ok=True)
CLAUDE_STUB = os.path.join(SCRATCH, "bin", "claude")
with open(CLAUDE_STUB, "w") as _handle:
    _handle.write("#!/bin/sh\necho 'claude stand-in (tests)' >&2\nexit 1\n")
os.chmod(CLAUDE_STUB, 0o755)
os.environ["HYPR_CLAUDE_CLI"] = CLAUDE_STUB
sys.path.insert(0, SCRIPTS)
# Bound to this checkout now, before any script puts the installed
# ~/.config/hypr/scripts in front of sys.path (launcher.py does): a page or
# power_state.py imported later in a test then still comes from here, and a
# test file never passes alone and fails after another one. Neither imports
# GTK or reads anything at import time (power_state reads the environment
# set above).
import settings_pages  # noqa: E402,F401
import power_state  # noqa: E402,F401

_loaded = {}


def import_script(filename, name=None):
    """Import scripts/<filename> as a module (once per run)."""
    name = name or filename.removesuffix(".py").replace("-", "_")
    if name not in _loaded:
        spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS, filename))
        module = importlib.util.module_from_spec(spec)
        argv, sys.argv = sys.argv, [filename]
        try:
            spec.loader.exec_module(module)
        finally:
            sys.argv = argv
            # Many scripts put the INSTALLED ~/.config/hypr/scripts first on
            # sys.path (launcher.py, the pages' common.py); a later plain
            # import (`from settings_pages import power`, `import power_state`)
            # would then load the installed copy, not this checkout's -- and
            # a test file passing alone would fail after one that imported
            # launcher.py. The copy under test goes back in front.
            if sys.path[:1] != [SCRIPTS]:
                sys.path.insert(0, SCRIPTS)
        _loaded[name] = module
    return _loaded[name]


def fake_power_supply(folder, battery=None, ac=None, extra=None):
    """Write a fake /sys/class/power_supply tree under FOLDER and return it
    (point ATRIUM_POWER_SUPPLY, or power_state's root= argument, at it).

    battery: None (a desktop) or the BATT attributes, e.g.
        {"status": "Discharging", "capacity": 40}; type Battery is implied,
        and current_now / voltage_now / charge_* get laptop-like defaults
        unless given (a value of None leaves that attribute out).
    ac: None (no charger entry) or True / False for ACAD's "online".
    extra: {name: {attribute: value}} for any other supply (a mouse:
        {"hidpp_battery_0": {"type": "Battery", "scope": "Device", ...}}).
    Calling it again on the same FOLDER changes only what it is given (the
    battery's defaults are written the first time only)."""
    supplies = dict(extra or {})
    if battery is not None:
        attrs = {}
        if not os.path.isdir(os.path.join(folder, "BATT")):     # the defaults only the first time
            attrs = {"type": "Battery", "present": 1, "status": "Discharging", "capacity": 80,
                     "current_now": 900000, "voltage_now": 12000000, "charge_now": 2400000,
                     "charge_full": 3000000, "charge_full_design": 5000000, "cycle_count": 255,
                     "charge_control_end_threshold": 100}
        attrs.update(battery)
        supplies["BATT"] = attrs
    if ac is not None:
        supplies["ACAD"] = {"type": "Mains", "online": 1 if ac else 0}
    for name, attrs in supplies.items():
        path = os.path.join(folder, name)
        os.makedirs(path, exist_ok=True)
        for key, value in attrs.items():
            target = os.path.join(path, key)
            if value is None:
                if os.path.exists(target):
                    os.remove(target)
                continue
            with open(target, "w") as handle:
                handle.write(f"{value}\n")
    os.makedirs(folder, exist_ok=True)
    return folder
