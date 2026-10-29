#!/usr/bin/env python3
"""Screenshots, screen recording, screen actions and gamemode: the choices
Settings > Screenshots & recording makes, kept in one small file that the
scripts doing the work read each time they run.

    capture-settings.py status            JSON: every value, its default, and
                                          what the machine has (tesseract
                                          languages, recorder, HDR screens,
                                          a recording or replay running,
                                          gamemode on, the profiles)
    capture-settings.py get KEY...        one value per line, defaults filled
                                          in and ~ expanded (for the scripts)
    capture-settings.py set KEY VALUE     check it, write it; says why not
    capture-settings.py reset KEY         back to the default
    capture-settings.py search-url TEXT   the "Look it up" address for TEXT

The keys (and who reads them):
    shot_dir        where screenshots go                 screenshot.sh
    shot_format     png | jpg | webp                     screenshot.sh
    shot_copy       on | off: a saved shot also goes     screenshot.sh
                    to the clipboard
    rec_dir         where recordings and replays go      record.sh
    rec_audio       desktop | both | mic | none          record.sh
    rec_fps         30 | 60 | 120 | 144                  record.sh
    rec_encoder     auto | gpu | cpu: who encodes; auto  record.sh (as
                    is gpu.py's pick                     REC_ENCODER)
    replay_seconds  how much the instant replay keeps    record.sh
    ocr_langs       tesseract languages, "eng+spa"       screenshot.sh ocr,
                                                         screen-actions.py
    search          the engine "Look it up" opens        screen-actions.py
    gamemode_blur, gamemode_shadow, gamemode_rounding, gamemode_gaps,
    gamemode_borders, gamemode_shader
                    on | off: what gamemode strips       lua/gamemode.lua
                    (shader: the screen filter and night
                    light's shader go too)
    gamemode_auto   on | off: Steam games switch it on   lua/gamemode.lua
    gamemode_hide_steam
                    on | off: tuck Steam away mid-game   lua/gamemode.lua

SDR / HDR is record.sh's own (`record.sh sdr|hdr`, kept in
$XDG_STATE_HOME/record-range); the game profiles are game-profiles.py's.

The file: $XDG_STATE_HOME/hypr/capture.conf, key=value lines -- the format
lua/shared.lua's read_kv reads, because Hyprland's Lua has no JSON parser.
A key that is missing means its default, so a fresh machine needs no file,
and a hand edit with a value this script would refuse is read as the
default too (and `status` says so). Nothing here restarts anything: each
reader looks again the next time it runs (gamemode the next time it turns
on, a replay buffer the next time it starts).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "hypr")
CONF = os.path.join(STATE_DIR, "capture.conf")
RECORD = os.path.join(HERE, "record.sh")
GAMES = os.path.join(HERE, "game-profiles.py")
BINDS = os.path.join(os.path.dirname(HERE), "lua", "binds.lua")

# The engines "Look it up" can open; {q} is the search text, URL-quoted.
ENGINES = {
    "duckduckgo": ("DuckDuckGo", "https://duckduckgo.com/?q={q}"),
    "google": ("Google", "https://www.google.com/search?q={q}"),
    "bing": ("Bing", "https://www.bing.com/search?q={q}"),
    "brave": ("Brave Search", "https://search.brave.com/search?q={q}"),
    "startpage": ("Startpage", "https://www.startpage.com/do/search?q={q}"),
    "ecosia": ("Ecosia", "https://www.ecosia.org/search?q={q}"),
    "kagi": ("Kagi", "https://kagi.com/search?q={q}"),
    "wikipedia": ("Wikipedia", "https://en.wikipedia.org/w/index.php?search={q}"),
}

ON_OFF = ("on", "off")
# key -> (default, the values it may take; None = checked by its own rule)
KEYS = {
    "shot_dir": ("~/Pictures/Screenshots", None),
    "shot_format": ("png", ("png", "jpg", "webp")),
    "shot_copy": ("on", ON_OFF),
    "rec_dir": ("~/Videos/Recordings", None),
    "rec_audio": ("desktop", ("desktop", "both", "mic", "none")),
    "rec_fps": ("60", ("30", "60", "120", "144")),
    "rec_encoder": ("auto", ("auto", "gpu", "cpu")),
    "replay_seconds": ("30", ("15", "30", "60", "120", "300")),
    "ocr_langs": ("eng+spa", None),
    "search": ("duckduckgo", tuple(ENGINES)),
    "gamemode_blur": ("on", ON_OFF),
    "gamemode_shadow": ("on", ON_OFF),
    "gamemode_rounding": ("on", ON_OFF),
    "gamemode_gaps": ("on", ON_OFF),
    "gamemode_borders": ("on", ON_OFF),
    "gamemode_shader": ("on", ON_OFF),
    "gamemode_auto": ("on", ON_OFF),
    "gamemode_hide_steam": ("on", ON_OFF),
}
FOLDERS = ("shot_dir", "rec_dir")
LANG = re.compile(r"^[A-Za-z0-9_]+$")


# -- the file ------------------------------------------------------------------
def read_kv(path=CONF):
    """The same rules as lua/shared.lua's read_kv: # comments, key=value,
    spaces around both trimmed."""
    out = {}
    try:
        with open(path) as handle:
            for line in handle:
                if line.lstrip().startswith("#"):
                    continue
                m = re.match(r"^\s*([\w.\-]+)\s*=\s*(.*?)\s*$", line)
                if m:
                    out[m[1]] = m[2]
    except OSError:
        pass
    return out


def write_kv(values, path=CONF):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as handle:
        handle.write("# Settings > Screenshots & recording (capture-settings.py). Missing = default.\n")
        for key in KEYS:
            if key in values:
                handle.write(f"{key}={values[key]}\n")
    os.replace(tmp, path)


def check(key, value):
    """The value as it is to be stored, or raise ValueError with the reason."""
    if key not in KEYS:
        raise ValueError(f"no setting {key!r} (have: {', '.join(KEYS)})")
    value = value.strip()
    allowed = KEYS[key][1]
    if allowed is not None:
        if value not in allowed:
            raise ValueError(f"{key} is one of {', '.join(allowed)}, not {value!r}")
        return value
    if key in FOLDERS:
        if not value or "\n" in value:
            raise ValueError("give a folder")
        home = os.path.expanduser("~")
        full = os.path.abspath(os.path.expanduser(value))
        if os.path.exists(full) and not os.path.isdir(full):
            raise ValueError(f"{full} is a file, not a folder")
        # Kept with ~ when it is under home: shorter, and the file still
        # means the same folder if the home folder ever moves.
        return "~" + full[len(home):] if full == home or full.startswith(home + "/") else full
    if key == "ocr_langs":
        langs = [l for l in re.split(r"[+,\s]+", value) if l]
        if not langs or not all(LANG.match(l) for l in langs):
            raise ValueError("languages are tesseract's names joined by +, like eng+spa")
        # Order kept, repeats dropped: tesseract tries them in this order.
        return "+".join(dict.fromkeys(langs))
    raise ValueError(f"no rule for {key}")


def values(raw=None):
    """Every key's value in force: what the file says when that is valid,
    else the default. Second: the keys whose file value was refused."""
    raw = read_kv() if raw is None else raw
    out, bad = {}, []
    for key, (default, _allowed) in KEYS.items():
        if key in raw:
            try:
                out[key] = check(key, raw[key])
                continue
            except ValueError:
                bad.append(key)
        out[key] = default
    return out, bad


def expand(key, value):
    return os.path.expanduser(value) if key in FOLDERS else value


def search_url(text, engine=None):
    engine = engine or values()[0]["search"]
    template = ENGINES.get(engine, ENGINES["duckduckgo"])[1]
    return template.replace("{q}", urllib.parse.quote(" ".join(text.split())[:300]))


# -- what the machine has ------------------------------------------------------
def run(*cmd, timeout=5, env=None):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              env=env).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def tesseract_langs():
    """Installed language data (osd is script detection, not a language);
    None when tesseract itself is missing."""
    if not shutil.which("tesseract"):
        return None
    lines = run("tesseract", "--list-langs").splitlines()[1:]
    return [l.strip() for l in lines if l.strip() and l.strip() != "osd"]


def monitors():
    try:
        return json.loads(run("hyprctl", "monitors", "-j") or "[]")
    except ValueError:
        return []


def option(name):
    try:
        return json.loads(run("hyprctl", "getoption", name, "-j") or "{}")
    except ValueError:
        return {}


def gamemode_on(answer):
    """True / False from `hyprctl getoption animations:enabled -j`, None
    when Hyprland did not say."""
    for key in ("bool", "int"):
        if key in answer:
            return not answer[key]
    return None


def shot_binds_follow(path=BINDS):
    """Whether the ALT+S family runs `screenshot.sh output|region|window`
    (and so follows the folder / format / copy settings) rather than
    hyprshot straight into lua/shared.lua's scrDir."""
    try:
        with open(path) as handle:
            text = handle.read()
    except OSError:
        return False
    return all(f"screenshot.sh {m}" in text for m in ("output", "region", "window"))


def encoder_env(value):
    """The REC_ENCODER record.sh takes for a rec_encoder value: "" for
    auto (gpu.py's pick), else gpu / cpu."""
    return value if value in ("gpu", "cpu") else ""


def record_reads(key, path=RECORD):
    """Whether record.sh asks for this key (`capture-settings.py get ...
    KEY`): a setting it does not read yet is shown as such on the page
    rather than looking like it works."""
    try:
        with open(path) as handle:
            return key in handle.read()
    except OSError:
        return False


def status():
    vals, bad = values()
    rec = run(RECORD, "status", env=dict(os.environ, REC_QUIET="1")).split()
    anim = option("animations:enabled")
    try:
        profiles = json.loads(run(GAMES, "list") or "{}")
    except ValueError:
        profiles = {}
    mons = monitors()
    return {
        "values": vals,
        "defaults": {k: d for k, (d, _a) in KEYS.items()},
        "invalid": bad,
        "folders": {k: expand(k, vals[k]) for k in FOLDERS},
        "folder_exists": {k: os.path.isdir(expand(k, vals[k])) for k in FOLDERS},
        "range": (run(RECORD, "range", env=dict(os.environ, REC_QUIET="1")).strip() or "sdr"),
        "hdr_screens": [m["name"] for m in mons
                        if str(m.get("colorManagementPreset", "")).startswith("hdr")],
        "recording": "recording" in rec,
        "replay": "replay" in rec,
        "tesseract": tesseract_langs(),
        "tools": {t: bool(shutil.which(t)) for t in
                  ("hyprshot", "grim", "slurp", "wl-copy", "satty", "magick", "gpu-screen-recorder")},
        "engines": {k: name for k, (name, _url) in ENGINES.items()},
        # Hyprland 0.56 answers {"bool": true}; older ones {"int": 1}.
        # Animations off is gamemode on (lua/gamemode.lua's own test).
        "gamemode_on": gamemode_on(anim),
        "profiles": profiles,
        "shot_binds_follow": shot_binds_follow(),
        "encoder_followed": record_reads("rec_encoder"),
        "conf": CONF,
    }


# -- commands ------------------------------------------------------------------
def main(argv):
    cmd = argv[0] if argv else ""
    if cmd == "status" and len(argv) == 1:
        print(json.dumps(status(), indent=1))
    elif cmd == "get" and len(argv) >= 2:
        vals, _bad = values()
        for key in argv[1:]:
            if key not in vals:
                sys.exit(f"capture-settings.py: no setting {key!r}")
            print(expand(key, vals[key]))
    elif cmd == "set" and len(argv) == 3:
        try:
            value = check(argv[1], argv[2])
        except ValueError as exc:
            sys.exit(f"capture-settings.py: {exc}")
        raw = read_kv()
        raw[argv[1]] = value
        write_kv(raw)
        print(f"{argv[1]}={value}")
    elif cmd == "reset" and len(argv) == 2:
        if argv[1] not in KEYS:
            sys.exit(f"capture-settings.py: no setting {argv[1]!r}")
        raw = read_kv()
        raw.pop(argv[1], None)
        write_kv(raw)
        print(f"{argv[1]}={KEYS[argv[1]][0]}")
    elif cmd == "search-url" and len(argv) >= 2:
        print(search_url(" ".join(argv[1:])))
    else:
        sys.exit(__doc__.strip())


if __name__ == "__main__":
    main(sys.argv[1:])
