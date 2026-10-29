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
import shutil
import sys
import tempfile

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
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
        _loaded[name] = module
    return _loaded[name]
