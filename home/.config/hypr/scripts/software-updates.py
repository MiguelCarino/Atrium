#!/usr/bin/env python3
"""Software updates: what is waiting, what the last upgrade did, and whether
the machine needs (or is safe for) a reboot -- for Settings > Software
updates, the search bar and the keys.

    software-updates.py status [--json]   everything below at once
    software-updates.py pending [--json]  the last check: packages (security
                                          ones marked, with their severity),
                                          flatpaks, when and how it ran
    software-updates.py system [--json]   reboot needed?, newest vs running
                                          kernel, the NVIDIA module for the
                                          newest kernel, the last upgrade
                                          (dnf history) and what
                                          safe-upgrade.sh recorded, snapshots
                                          before updates, the check interval
    software-updates.py firmware [--json] fwupd's pending firmware (read only)
    software-updates.py history [N] [--json]   the last N dnf transactions
    software-updates.py changes ID        `dnf history info ID` in a terminal
    software-updates.py check             check again now (the updates pill
                                          runs it; its cache is shared)
    software-updates.py upgrade           safe-upgrade.sh in a terminal
    software-updates.py interval [1h|3h|6h|12h|24h|login]
                                          how often the pill checks by itself
                                          (no value: say the current one)

Nothing here installs anything or needs root. The one source of each fact:

  pending    the cache waybar/scripts/updates.sh writes on every check
             ($XDG_RUNTIME_DIR/waybar-updates.tsv, the same one the updates
             panel reads) -- so this never runs a second `dnf check-update`.
             "Check" signals the pill (SIGRTMIN+8) to run one; with no bar
             running it runs updates.sh itself. Security marks come from
             `dnf --cacheonly advisory list --security --updates`: only the
             metadata that check already downloaded, no network.
  upgrade    waybar/scripts/safe-upgrade.sh, in kitty, exactly as the pill's
             panel starts it: btrfs snapshot (or snapper's own pre/post pair),
             dnf upgrade, build + check the NVIDIA module for the newest
             kernel, flatpak, firmware listing. It records how that went in
             $XDG_STATE_HOME/hypr/last-upgrade.tsv, read back here.
  reboot     `needs-restarting -r` (exit 1 = a core library, the kernel or
             a service updated since boot), and the newest installed
             kernel-core against `uname -r`.
  nvidia     live, read only: the installed driver (xorg-x11-drv-nvidia)
             against `modinfo -k <newest kernel> nvidia` -- a mismatch or no
             module means do not reboot into that kernel yet.
  interval   the "interval" of custom/updates in ~/.config/waybar/config;
             setting it rewrites that one line and restarts the bar with
             waybar/scripts/bar-restart.sh (what ALT+G runs), so the new
             interval is live at once and survives a Hyprland reload and a
             re-login. Not `systemctl --user reload` / SIGUSR2: waybar 0.15
             rebuilds its modules in place on that and can abort (the
             fork/pthread_cancel race bar-restart.sh describes). Only when
             waybar.service is running -- a bar that is off stays off. "login" is waybar's "once": a
             check each time the bar starts, then only when asked.
  snapshots  snapshots.py status (snapper, set up by setup-root.sh); without
             snapper, safe-upgrade.sh's own read-only snapshots in
             /.snapshots-pre-upgrade.
"""
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
WAYBAR_SCRIPTS = os.path.expanduser("~/.config/waybar/scripts")
UPDATES_SH = os.path.join(WAYBAR_SCRIPTS, "updates.sh")
SAFE_UPGRADE = os.path.join(WAYBAR_SCRIPTS, "safe-upgrade.sh")
SNAPSHOTS = os.path.join(HERE, "snapshots.py")
BAR_RESTART = os.path.join(WAYBAR_SCRIPTS, "bar-restart.sh")
WAYBAR_CONFIG = os.environ.get("SOFTWARE_UPDATES_WAYBAR_CONFIG") or os.path.expanduser("~/.config/waybar/config")
CACHE = os.environ.get("SOFTWARE_UPDATES_CACHE") or os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"),
                                                                 "waybar-updates.tsv")
RECORD = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                      "hypr", "last-upgrade.tsv")
PRE_UPGRADE_DIR = "/.snapshots-pre-upgrade"       # safe-upgrade.sh's SNAPDIR
SIGNAL = 8                                        # custom/updates
TERMINAL = ["kitty", "--class", "software-updates", "--title", "Software updates"]

# The choices offered for the pill's own check, as waybar "interval" values.
INTERVALS = [("1h", 3600), ("3h", 10800), ("6h", 21600), ("12h", 43200), ("24h", 86400), ("login", "once")]
INTERVAL_NAMES = {"1h": "every hour", "3h": "every 3 hours", "6h": "every 6 hours",
                  "12h": "twice a day", "24h": "once a day", "login": "at login only"}
# Which dnf transactions count as "an update" (rather than an install or a
# removal): dnf's subcommand -- the first word after "dnf" that is not an
# option -- is one of these. Not a search of the whole line: "dnf install
# update-motd" is an install. PackageKit (GNOME Software) transactions have
# no dnf command line and show up as other changes.
UPDATE_COMMANDS = {"upgrade", "update", "up", "upgrade-minimal", "update-minimal", "distro-sync",
                   "dsync", "offline-upgrade", "system-upgrade"}
DNF_NAMES = {"dnf", "dnf5", "dnf-3", "yum"}


def run(*cmd, timeout=30):
    """(exit status, stdout); 127 when the command is missing, 124 on timeout."""
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return done.returncode, done.stdout
    except FileNotFoundError:
        return 127, ""
    except subprocess.TimeoutExpired:
        return 124, ""
    except (OSError, subprocess.SubprocessError):
        return 1, ""


def read(path):
    try:
        with open(path) as handle:
            return handle.read()
    except OSError:
        return None


# -- pure parsing (tests/test_settings_updates.py) ------------------------------------
def parse_cache(text):
    """updates.sh's cache -> {checked, status, pkgs: [(name.arch, version)],
    flatpaks: [app id]}; None when there is no cache yet (no check since
    boot -- it lives in $XDG_RUNTIME_DIR)."""
    if text is None:
        return None
    data = {"checked": 0, "status": "unknown", "pkgs": [], "flatpaks": []}
    for line in text.splitlines():
        f = line.split("\t")
        if f[0] == "checked" and len(f) > 1 and f[1].isdigit():
            data["checked"] = int(f[1])
        elif f[0] == "status" and len(f) > 1:
            data["status"] = f[1]
        elif f[0] == "pkg" and len(f) > 2:
            data["pkgs"].append((f[1], f[2]))
        elif f[0] == "flatpak" and len(f) > 1 and f[1]:
            data["flatpaks"].append(f[1])
    return data


def nevra_key(nevra):
    """"PackageKit-command-not-found-1.4.0-1.fc44.x86_64" ->
    "PackageKit-command-not-found.x86_64" (the cache's name.arch), or None."""
    head, dot, arch = nevra.rpartition(".")
    parts = head.rsplit("-", 2)
    if not dot or len(parts) != 3 or not parts[0]:
        return None
    return f"{parts[0]}.{arch}"


SEVERITY_RANK = {"critical": 4, "important": 3, "moderate": 2, "low": 1}


def security_marks(advisories):
    """dnf advisory JSON rows -> {name.arch: {"severity", "advisory"}}, the
    worst severity when several advisories cover one package."""
    marks = {}
    for adv in advisories or []:
        key = nevra_key(adv.get("nevra", ""))
        if not key or adv.get("type", "security") != "security":
            continue
        sev = (adv.get("severity") or "").strip() or "None"
        old = marks.get(key)
        if old is None or SEVERITY_RANK.get(sev.lower(), 0) > SEVERITY_RANK.get(old["severity"].lower(), 0):
            marks[key] = {"severity": sev, "advisory": adv.get("name", "")}
    return marks


def dnf_subcommand(command_line):
    """"dnf -y upgrade --refresh" -> "upgrade"; "" when there is none."""
    words = (command_line or "").split()
    for i, w in enumerate(words):
        if os.path.basename(w) in DNF_NAMES:
            words = words[i + 1:]
            break
    return next((w for w in words if not w.startswith("-")), "")


def describe(command_line):
    """A dnf command line as a title: "dnf -y install --nogpgcheck
    /tmp/akmods.X/results/kmod-nvidia-7.2.11-...rpm" -> "install kmod-nvidia
    (akmods)"; options dropped, package files shortened to their names."""
    if not command_line:
        return "PackageKit (Software)"
    words = command_line.split()
    for i, w in enumerate(words):
        if os.path.basename(w) in DNF_NAMES:
            words = words[i + 1:]
            break
    kept = [re.sub(r"-\d.*\.rpm$", "", os.path.basename(w)) if "/" in w else w
            for w in words if not w.startswith("-")]
    # A bare "dnf update" updated everything; say so instead of one word.
    if len(kept) == 1 and kept[0] in UPDATE_COMMANDS:
        kept.append("(everything)")
    text = " ".join(kept) or command_line
    return text + (" (akmods)" if "/akmods" in command_line else "")


def last_update(history):
    """dnf history JSON (newest first) -> (the last transaction that was an
    update, the last transaction of any kind); either may be None. Only
    successful ones."""
    update = other = None
    for t in history or []:
        if t.get("status", "Ok") != "Ok":
            continue
        if other is None:
            other = t
        if update is None and dnf_subcommand(t.get("command_line")) in UPDATE_COMMANDS:
            update = t
        if update and other:
            break
    return update, other


def reboot_verdict(rc, output, newest_kernel, running_kernel):
    """needs-restarting -r's exit status and text, and the kernels ->
    {"needed": True|False|None, "reasons": [...]}. None = could not tell."""
    reasons = [line.strip().lstrip("*").strip() for line in (output or "").splitlines()
               if line.strip().startswith("*")]
    needed = {0: False, 1: True}.get(rc)
    if newest_kernel and running_kernel and newest_kernel != running_kernel:
        needed = True
        if not any(r.startswith("kernel") for r in reasons):
            reasons.insert(0, f"kernel {newest_kernel} installed, running {running_kernel}")
    return {"needed": needed, "reasons": reasons}


def nvidia_verdict(driver, module):
    """The installed driver version and the newest kernel's module version ->
    "none" (no NVIDIA driver), "ok", "missing" or "mismatch" -- the same words
    safe-upgrade.sh records."""
    if not driver:
        return "none"
    if not module:
        return "missing"
    return "ok" if module == driver else "mismatch"


def parse_record(text):
    """safe-upgrade.sh's last-upgrade.tsv -> {key: value} with "finished" an
    int, or None."""
    if not text:
        return None
    rec = {}
    for line in text.splitlines():
        key, tab, value = line.partition("\t")
        if tab:
            rec[key] = value
    try:
        rec["finished"] = int(rec.get("finished", ""))
    except ValueError:
        return None
    return rec


_BLOCK = re.compile(r'"custom/updates"\s*:\s*\{')


def _block_span(text):
    """(start, end) of the custom/updates object's body in the waybar config,
    braces counted (the config's comments hold no braces inside that block)."""
    m = _BLOCK.search(text)
    if not m:
        return None
    depth, i = 1, m.end()
    while i < len(text) and depth:
        depth += {"{": 1, "}": -1}.get(text[i], 0)
        i += 1
    return (m.end(), i - 1) if depth == 0 else None


_INTERVAL = re.compile(r'("interval"\s*:\s*)("once"|\d+)')


def get_interval(text):
    """The pill's interval from the waybar config: seconds (int), "once", or
    None when it has none (waybar then runs it once)."""
    span = _block_span(text or "")
    if not span:
        return None
    m = _INTERVAL.search(text, span[0], span[1])
    if not m:
        return "once"
    return "once" if m.group(2) == '"once"' else int(m.group(2))


def set_interval(text, value):
    """The waybar config with custom/updates' interval set to value (seconds
    or "once"); the rest of the file, comments included, as it was. Raises
    ValueError when there is no custom/updates block."""
    span = _block_span(text)
    if not span:
        raise ValueError("no custom/updates in the waybar config")
    literal = '"once"' if value == "once" else str(int(value))
    m = _INTERVAL.search(text, span[0], span[1])
    if m:
        return text[:m.start(2)] + literal + text[m.end(2):]
    # No interval yet: add one as the block's first key, indented like the next line.
    nl = text.find("\n", span[0])
    nxt = re.match(r"[ \t]*", text[nl + 1:]).group(0) if nl != -1 else "        "
    return text[:span[0]] + f"\n{nxt}\"interval\": {literal}," + text[span[0]:]


def interval_name(value):
    """3600 -> "1h"; "once" -> "login"; anything else -> e.g. "every 90 min"."""
    for name, v in INTERVALS:
        if v == value:
            return name
    if isinstance(value, int):
        return f"{value // 60} min" if value % 3600 else f"{value // 3600}h"
    return "login"


def interval_value(name):
    """"6h" -> 21600, "login"/"once" -> "once"; ValueError otherwise."""
    name = name.strip().lower()
    for n, v in INTERVALS:
        if name == n or (name == "once" and v == "once"):
            return v
    raise ValueError(f"interval is one of {', '.join(n for n, _ in INTERVALS)}")


def parse_firmware(text):
    """fwupdmgr get-updates --json -> [{device, current, new, summary}]."""
    try:
        data = json.loads(text or "")
    except ValueError:
        return []
    out = []
    for dev in data.get("Devices", []) if isinstance(data, dict) else []:
        releases = dev.get("Releases") or [{}]
        rel = releases[0]
        out.append({"device": dev.get("Name", "?"), "vendor": dev.get("Vendor", ""),
                    "current": dev.get("Version", ""), "new": rel.get("Version", ""),
                    "summary": rel.get("Summary", "") or rel.get("Name", "")})
    return out


# -- facts (each one command, bounded) ----------------------------------------------
def pending():
    data = parse_cache(read(CACHE))
    try:
        data_mtime = os.path.getmtime(CACHE)
    except OSError:
        data_mtime = 0
    if data is None:
        return {"cache": False, "mtime": 0, "checked": 0, "status": "never", "pkgs": [], "flatpaks": [],
                "security": None, "kernel": False}
    marks = None
    if data["pkgs"]:
        rc, out = run("nice", "-n", "19", "dnf", "--cacheonly", "-q", "advisory", "list", "--security",
                      "--updates", "--json", timeout=60)
        if rc == 0:
            try:
                marks = security_marks(json.loads(out or "[]"))
            except ValueError:
                marks = None
    pkgs = []
    for name, version in sorted(data["pkgs"]):
        mark = (marks or {}).get(name)
        pkgs.append({"name": name, "version": version,
                     "security": mark["severity"] if mark else None,
                     "advisory": mark["advisory"] if mark else None})
    return {"cache": True, "mtime": data_mtime, "checked": data["checked"], "status": data["status"],
            "pkgs": pkgs, "flatpaks": sorted(data["flatpaks"]),
            "security": None if marks is None and data["pkgs"] else sum(1 for p in pkgs if p["security"]),
            "kernel": any(p["name"].startswith("kernel-core.") for p in pkgs)}


def newest_kernel():
    rc, out = run("rpm", "-q", "--qf", "%{BUILDTIME} %{VERSION}-%{RELEASE}.%{ARCH}\n", "kernel-core")
    rows = sorted((int(t), k) for t, _s, k in (l.partition(" ") for l in out.splitlines()) if t.isdigit())
    return rows[-1][1] if rc == 0 and rows else None


def nvidia(kernel):
    rc, out = run("rpm", "-q", "--qf", "%{VERSION}\n", "xorg-x11-drv-nvidia")
    versions = [v for v in out.split() if re.match(r"^\d", v)] if rc == 0 else []
    driver = sorted(versions, key=lambda v: [int(x) if x.isdigit() else 0 for x in v.split(".")])[-1] \
        if versions else None
    module = None
    if driver and kernel:
        rc, out = run("modinfo", "-k", kernel, "-F", "version", "nvidia")
        module = out.strip() or None if rc == 0 else None
    loaded = (read("/sys/module/nvidia/version") or "").strip() or None
    return {"driver": driver, "module": module, "loaded": loaded, "kernel": kernel,
            "verdict": nvidia_verdict(driver, module)}


def history(limit=10):
    rc, out = run("dnf", "-q", "history", "list", "--json", timeout=30)
    try:
        rows = json.loads(out) if rc == 0 else []
    except ValueError:
        rows = []
    rows = sorted(rows, key=lambda t: t.get("id", 0), reverse=True)
    for t in rows:
        t["title"] = describe(t.get("command_line"))
    return rows[:limit] if limit else rows


def snapshot_state():
    rc, out = run(SNAPSHOTS, "status", timeout=30)
    status = out.strip() or "unknown"
    try:
        pre = sorted(n for n in os.listdir(PRE_UPGRADE_DIR) if n.startswith("pre-upgrade-"))
    except OSError:
        pre = []
    return {"snapper": status != "not set up" and rc == 0, "status": status, "pre_upgrade": pre[::-1]}


def system():
    kernel = newest_kernel()
    running = os.uname().release
    rc, out = run("needs-restarting", "-r", timeout=60)
    upd, other = last_update(history(0))
    return {"running_kernel": running, "newest_kernel": kernel,
            "reboot": reboot_verdict(rc, out, kernel, running),
            "nvidia": nvidia(kernel),
            "last_update": upd, "last_change": other,
            "record": parse_record(read(RECORD)),
            "snapshots": snapshot_state(),
            "interval": get_interval(read(WAYBAR_CONFIG)),
            "upgrade_running": run("pgrep", "-f", "safe-upgrade.sh")[0] == 0}


def firmware():
    rc, out = run("fwupdmgr", "get-updates", "--json", "--no-unreported-check", timeout=90)
    if rc == 127:
        return {"available": False, "devices": []}
    # fwupdmgr exits 2 for "no updates"; JSON comes either way.
    return {"available": True, "devices": parse_firmware(out), "error": rc not in (0, 2) and not out.strip()}


# -- actions --------------------------------------------------------------------------
def check():
    """Ask the pill to check (it rewrites the cache); no bar -> run its script."""
    if run("pkill", f"-RTMIN+{SIGNAL}", "-x", "waybar")[0] != 0:
        subprocess.Popen([UPDATES_SH], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)


def upgrade():
    subprocess.Popen([*TERMINAL, "-e", SAFE_UPGRADE], stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


def changes(tid):
    subprocess.Popen([*TERMINAL, "--hold", "-e", "dnf", "history", "info", str(int(tid))],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def write_interval(name):
    value = interval_value(name)
    text = read(WAYBAR_CONFIG)
    if text is None:
        raise ValueError(f"cannot read {WAYBAR_CONFIG}")
    new = set_interval(text, value)
    if new != text:
        mode = os.stat(WAYBAR_CONFIG).st_mode & 0o7777
        tmp = WAYBAR_CONFIG + ".tmp"
        with open(tmp, "w") as handle:
            handle.write(new)
        os.chmod(tmp, mode)
        os.replace(tmp, WAYBAR_CONFIG)
        # A scratch config (the tests) never touches the live bar.
        if not os.environ.get("SOFTWARE_UPDATES_WAYBAR_CONFIG") and \
                run("systemctl", "--user", "is-active", "--quiet", "waybar.service", timeout=5)[0] == 0:
            run(BAR_RESTART, timeout=20)
    return value


# -- text output ----------------------------------------------------------------------
def when(epoch):
    return time.strftime("%a %d %b %H:%M", time.localtime(epoch)) if epoch else "never"


def say_pending(p):
    if not p["cache"]:
        print("updates: no check since boot -- `software-updates.py check` runs one")
        return
    sec = p["security"]
    print(f"updates: {len(p['pkgs'])} package(s)"
          + (f" ({sec} security)" if sec else "") + f", {len(p['flatpaks'])} flatpak(s)"
          + f"  ·  checked {when(p['checked'])} ({p['status']})")
    for pkg in p["pkgs"]:
        print(f"  {pkg['name']:<44} {pkg['version']}" + (f"  [security: {pkg['security']}]" if pkg["security"] else ""))
    for app in p["flatpaks"]:
        print(f"  flatpak {app}")


def say_system(s):
    r = s["reboot"]
    print("reboot: " + {True: "needed", False: "not needed", None: "unknown"}[r["needed"]]
          + (f" ({'; '.join(r['reasons'][:3])})" if r["reasons"] else ""))
    print(f"kernel: running {s['running_kernel']}, newest {s['newest_kernel']}")
    n = s["nvidia"]
    print(f"nvidia: {n['verdict']}  (driver {n['driver']}, module for newest kernel {n['module']}, loaded {n['loaded']})")
    u = s["last_update"]
    print(f"last update: {when(u['end_time']) if u else 'none in dnf history'}"
          + (f"  ({u['command_line']}, {u['altered_count']} packages, transaction {u['id']})" if u else ""))
    rec = s["record"]
    if rec:
        print(f"last safe-upgrade: {when(rec['finished'])}  nvidia {rec.get('nvidia')}  reboot {rec.get('reboot')}")
    print(f"snapshots: {s['snapshots']['status']}")
    print(f"check interval: {interval_name(s['interval'])}")


def main(argv):
    want_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    cmd = argv[0] if argv else "status"
    out = None
    if cmd == "pending":
        out = pending()
        if not want_json:
            return say_pending(out)
    elif cmd == "system":
        out = system()
        if not want_json:
            return say_system(out)
    elif cmd == "firmware":
        out = firmware()
        if not want_json:
            for d in out["devices"]:
                print(f"{d['device']}: {d['current']} -> {d['new']}  {d['summary']}")
            if not out["devices"]:
                print("firmware: up to date" if out["available"] else "firmware: fwupd not installed")
            return
    elif cmd == "status":
        out = {"pending": pending(), "system": system(), "firmware": firmware()}
        if not want_json:
            say_pending(out["pending"])
            say_system(out["system"])
            print(f"firmware: {len(out['firmware']['devices'])} update(s)")
            return
    elif cmd == "history":
        out = history(int(argv[1]) if len(argv) > 1 and argv[1].isdigit() else 10)
        if not want_json:
            for t in out:
                print(f"{t.get('id'):>5}  {when(t.get('end_time'))}  {t.get('altered_count', 0):>4}  "
                      f"{t['title']}")
            return
    elif cmd == "changes" and len(argv) > 1 and argv[1].isdigit():
        return changes(argv[1])
    elif cmd == "check":
        return check()
    elif cmd == "upgrade":
        return upgrade()
    elif cmd == "interval":
        if len(argv) > 1:
            try:
                write_interval(argv[1])
            except (ValueError, OSError) as err:
                print(err, file=sys.stderr)
                return 2
        value = get_interval(read(WAYBAR_CONFIG))
        out = {"interval": interval_name(value), "value": value}
        if not want_json:
            print(f"{out['interval']} ({INTERVAL_NAMES.get(out['interval'], out['interval'])})")
            return
    else:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]) or 0)
