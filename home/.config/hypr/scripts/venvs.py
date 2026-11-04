#!/usr/bin/env python3
"""The desktop's Python venvs: Piper (speech), faster-whisper (dictation and
captions) and OpenCV (presence). Each lives in ~/.local/share/<name>/venv.

    venvs.py status [--json]           each venv: missing, ok, or stale (built for another Python)
    venvs.py rebuild NAME...           build (or rebuild) these: tts, voice, presence
    venvs.py rebuild --stale           rebuild every venv that exists but is stale
    venvs.py check                     at login (lua/autostart.lua): one notification per
                                       Python version when a venv went stale

WHY: a venv is tied to the Python that made it. A Fedora upgrade moves
python3 on (Fedora 45: 3.14 -> 3.15) and removes the old one; the venv's
site-packages are then invisible and speech, dictation and presence stop.

The venvs use --system-site-packages, for Fedora's python3-onnxruntime
(packages/dnf.txt): PyPI has no onnxruntime wheel for a new Python for months
after Fedora ships it, and Fedora's build always matches python3. Everything
else comes from PyPI.

A rebuild keeps the old venv as venv.old until the new one imports, and puts
it back when the new one fails, so a failed rebuild costs nothing. The voice
venv takes the CUDA 12 libraries (about 2.5 GB) only on a machine with the
NVIDIA driver; without it dictation runs on the CPU."""
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
HOME = os.path.expanduser("~")
NOTIFY = os.path.join(HERE, "notify")

# name -> (what it is, pip packages, the import that proves it works)
VENVS = {
    "tts": ("Speech (Piper)", ["piper-tts"], "import piper, onnxruntime"),
    "voice": ("Dictation (faster-whisper)", ["faster-whisper"], "import faster_whisper, ctranslate2"),
    "presence": ("Presence (OpenCV)", ["opencv-python-headless", "numpy"], "import cv2"),
}
CUDA = ["nvidia-cublas-cu12", "nvidia-cudnn-cu12", "nvidia-cuda-nvrtc-cu12"]


def data_home():
    return os.environ.get("XDG_DATA_HOME") or os.path.join(HOME, ".local", "share")


def state_file():
    return os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.join(HOME, ".local", "state"),
                        "hypr", "venvs-notified")


def venv_dir(name, root=None):
    return os.path.join(root or data_home(), name, "venv")


def this_python():
    return f"{sys.version_info.major}.{sys.version_info.minor}"


def built_for(venv):
    """'3.14' from pyvenv.cfg's version line, or None (not a venv)."""
    try:
        with open(os.path.join(venv, "pyvenv.cfg"), encoding="utf-8") as f:
            for line in f:
                key, _, value = line.partition("=")
                if key.strip() in ("version", "version_info"):
                    return ".".join(value.strip().split(".")[:2])
    except OSError:
        pass
    return None


def state(name, root=None, python=None):
    """missing | ok | stale, and the Python it was built for."""
    venv = venv_dir(name, root)
    if not os.path.exists(os.path.join(venv, "bin", "python")):
        return "missing", None
    was = built_for(venv)
    return ("ok" if was == (python or this_python()) else "stale"), was


def has_nvidia():
    return os.path.exists("/proc/driver/nvidia/version")


def packages(name, nvidia=None):
    pkgs = list(VENVS[name][1])
    if name == "voice" and (has_nvidia() if nvidia is None else nvidia):
        pkgs += CUDA
    return pkgs


def rebuild(name, root=None, run=subprocess.run, log=print):
    """Build NAME's venv fresh; the old one comes back if this fails."""
    venv = venv_dir(name, root)
    old = venv + ".old"
    shutil.rmtree(old, ignore_errors=True)
    if os.path.exists(venv):
        os.rename(venv, old)
    py = os.path.join(venv, "bin", "python")
    steps = [[sys.executable, "-m", "venv", "--system-site-packages", venv],
             [py, "-m", "pip", "install", "-q", "--disable-pip-version-check", *packages(name)],
             [py, "-c", VENVS[name][2]]]
    log(f"{name}: building for Python {this_python()} ({' '.join(packages(name))})")
    for cmd in steps:
        if run(cmd, check=False).returncode != 0:
            log(f"{name}: failed at: {' '.join(cmd[:4])}")
            shutil.rmtree(venv, ignore_errors=True)
            if os.path.exists(old):
                os.rename(old, venv)
                log(f"{name}: the previous venv is back")
            return False
    shutil.rmtree(old, ignore_errors=True)
    log(f"{name}: ok")
    return True


def stale_names(root=None):
    return [n for n in VENVS if state(n, root)[0] == "stale"]


def check(root=None, notify=None):
    """Notify once per Python version about stale venvs; returns their names."""
    stale = stale_names(root)
    path = state_file()
    try:
        with open(path, encoding="utf-8") as f:
            seen = f.read().strip()
    except OSError:
        seen = ""
    if not stale or seen == this_python():
        return stale
    names = ", ".join(VENVS[n][0] for n in stale)
    (notify or (lambda *a: subprocess.run([NOTIFY, *a], capture_output=True, timeout=10, check=False)))(
        "-a", "Python", "-u", "normal", f"Python {this_python()}: rebuild needed",
        f"{names} {'was' if len(stale) == 1 else 'were'} built for an older Python and will not start. "
        "Run ~/.config/hypr/scripts/venvs.py rebuild --stale")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(this_python())
    return stale


def main(argv):
    cmd, rest = (argv[0], argv[1:]) if argv else ("status", [])
    if cmd == "status":
        rows = {n: dict(zip(("state", "built_for"), state(n))) for n in VENVS}
        if "--json" in rest:
            print(json.dumps({"python": this_python(), "venvs": rows}))
        else:
            for n, r in rows.items():
                print(f"{n:9} {r['state']:8} {('Python ' + r['built_for']) if r['built_for'] else ''}")
        return 0
    if cmd == "rebuild":
        names = stale_names() if rest == ["--stale"] else rest
        unknown = [n for n in names if n not in VENVS]
        if unknown or not (names or rest == ["--stale"]):
            print(f"venvs: rebuild NAME... (of {', '.join(VENVS)}) or --stale", file=sys.stderr)
            return 2
        failed = [n for n in names if not rebuild(n)]
        if not names:
            print("venvs: nothing stale")
        return 1 if failed else 0
    if cmd == "check":
        check()
        return 0
    print(__doc__.split("\n\n")[1], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
