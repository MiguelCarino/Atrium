#!/usr/bin/env python3
"""Desktop health check: is every background piece of this desktop running
and well?

    doctor.py              a readable report, worst first
    doctor.py --json       the same as JSON ({"checks": [...], "worst": ...})
    doctor.py --fix        restart the user units that failed or stopped,
                           then check again
    doctor.py bar          waybar custom-module JSON: nothing when all is
                           well, an icon and a count when not (tooltip: what)

Each check is ok / warn / fail (info = only shown in the report):

    units       every unit a *.target.wants/ folder in ~/.config/systemd/user
                pulls in (waybar, mako, the launcher, screen colour, the
                clipboard, auto-DND, ... and whatever is added later --
                activity log, OSD, game profiles, automount, phone, hypr
                guard, dotfiles backup: found the same way, no list to keep
                up to date): a service must be running, a timer must be
                waiting and its last run must have succeeded. Plus anything
                `systemctl --user --failed` names.
    hyprland    `hyprctl configerrors` is empty
    screen      screen-color.py's daemon is alive (it holds the colour
                matrices; without it the night light does nothing)
    launcher    its service runs and its socket exists. (Not connected to:
                an empty request on that socket OPENS the launcher.)
    clipboard   cliphist's store is there and readable
    disk        / and /home have at least 10 % free (5 % = fail)
    journal     errors (priority err and worse) from the desktop's units in
                the last hour
    lm studio   its server answers on :1234 (info only: it starts on demand)
    dotfiles    your dotfiles repo's sync.sh --check (desktop.conf's dotfiles=,
                desktop_conf.py): home and the repo agree and nothing is
                unpushed (warn only). No repo set: no such line at all
    backup      backup.py (restic / kopia), once one is set up: the last good
                backup is under a week old (backup.py WARN_DAYS; warn past it, when
                the last run failed); not set up: no line
    snapshots   snapper, if installed: the newest snapshot is under 2 days old
                (installed but not set up yet is info, not a warning)
    health      the last nightly checkup (health.py, the self-healing one):
                warn while fixes wait for your OK or it found something
                failing that you have not seen; the report adds its worst
                findings, explained (health.py report has all of them)

Takes about a second. Logs what --fix restarts through desklog (journal tag
"doctor").
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import desklog  # noqa: E402
import desktop_conf  # noqa: E402

HOME = os.path.expanduser("~")
UNIT_DIR = os.path.join(HOME, ".config", "systemd", "user")
RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
CLIPHIST_DB = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.join(HOME, ".cache"), "cliphist", "db")
DISK_WARN, DISK_FAIL = 0.10, 0.05
SNAPSHOT_MAX_AGE = 2 * 86400
LEVELS = {"ok": 0, "info": 0, "warn": 1, "fail": 2}
ICON = ""             # stethoscope


def sh(*cmd, timeout=10):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return out.returncode, out.stdout, out.stderr
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, "", str(exc)


def check(name, level, text, unit=None):
    return {"name": name, "level": level, "text": text, **({"unit": unit} if unit else {})}


# -- units ----------------------------------------------------------------------
def wanted_units():
    """Units the user's own targets pull in (the *.target.wants/ links)."""
    out = []
    try:
        for entry in sorted(os.listdir(UNIT_DIR)):
            if entry.endswith(".wants") and os.path.isdir(os.path.join(UNIT_DIR, entry)):
                out += [u for u in sorted(os.listdir(os.path.join(UNIT_DIR, entry))) if u not in out]
    except OSError:
        pass
    return out


def unit_props(units):
    """{unit: {prop: value}} from one `systemctl show`."""
    if not units:
        return {}
    _, out, _ = sh("systemctl", "--user", "show", "-p",
                   "Id,LoadState,ActiveState,SubState,Result,Type,Triggers,RemainAfterExit,ConditionResult", *units)
    props, cur = {}, {}
    for line in out.splitlines() + [""]:
        if not line:
            if cur.get("Id"):
                props[cur["Id"]] = cur
            cur = {}
            continue
        key, _, value = line.partition("=")
        cur[key] = value
    return props


def service_state(p):
    """(level, text) for a wanted service from its `systemctl show` props.
    Not running is only a failure for a daemon that should be: a oneshot, a
    unit that did its work and exited cleanly with RemainAfterExit, and one
    whose Condition...= said "not now" (welcome.service once it has been
    seen) all ended the way they are meant to."""
    active, result = p.get("ActiveState"), p.get("Result")
    if active == "failed":
        return "fail", f"failed ({result})"
    if active == "active":
        return "ok", p.get("SubState") or "running"
    if p.get("ConditionResult") == "no":
        return "ok", "not needed now (its condition is not met)"
    if p.get("Type") == "oneshot":
        return "ok", p.get("SubState") or "done"
    if p.get("RemainAfterExit") == "yes" and result in (None, "", "success"):
        return "ok", "ran and exited"
    return "fail", f"not running ({active})"


def check_units():
    units = wanted_units()
    props = unit_props(units)
    timers = [u for u in units if u.endswith(".timer")]
    triggered = {}
    for t in timers:
        for svc in props.get(t, {}).get("Triggers", "").split():
            triggered[svc] = t
    svc_props = unit_props(list(triggered))
    results = []
    for unit in units:
        p = props.get(unit, {})
        if p.get("LoadState") == "not-found":
            results.append(check("units", "warn", f"{unit}: enabled but its unit file is gone", unit))
        elif unit.endswith(".timer"):
            if p.get("ActiveState") != "active":
                results.append(check("units", "fail", f"{unit}: not waiting ({p.get('ActiveState')})", unit))
            else:
                results.append(check("units", "ok", f"{unit}: waiting", unit))
        else:
            level, text = service_state(p)
            results.append(check("units", level, f"{unit}: {text}", unit))
    for svc, timer in triggered.items():
        p = svc_props.get(svc, {})
        if p.get("Result") not in (None, "success"):
            results.append(check("units", "warn", f"{svc} (from {timer}): last run {p.get('Result')}", svc))
    _, out, _ = sh("systemctl", "--user", "list-units", "--failed", "--plain", "--no-legend")
    for line in out.splitlines():
        unit = line.split()[0] if line.split() else ""
        if unit and unit not in units:
            results.append(check("units", "fail", f"{unit}: failed", unit))
    return results


# -- the rest -------------------------------------------------------------------
def check_hyprland():
    rc, out, err = sh("hyprctl", "configerrors", "-j")
    if rc != 0:
        return check("hyprland", "warn", f"hyprctl did not answer: {err.strip()[:80]}")
    try:
        errors = [e for e in json.loads(out or "[]") if e.strip()]
    except ValueError:
        errors = [out.strip()] if out.strip() else []
    if errors:
        return check("hyprland", "fail", f"config errors: {errors[0][:120]}"
                     + (f" (+{len(errors) - 1} more)" if len(errors) > 1 else ""))
    return check("hyprland", "ok", "config loads without errors")


def pid_alive(path):
    try:
        with open(path) as handle:
            os.kill(int(handle.read().strip()), 0)
        return True
    except (OSError, ValueError):
        return False


def check_screen():
    if not os.path.exists(os.path.join(UNIT_DIR, "screen-color.service")):
        return check("screen", "info", "screen-color is not set up")
    if pid_alive(os.path.join(RUNTIME, "screen-color.pid")):
        return check("screen", "ok", "colour daemon running")
    return check("screen", "fail", "screen-color daemon is not running (night light / brightness do nothing)")


def check_launcher():
    if not os.path.exists(os.path.join(RUNTIME, "launcher.sock")):
        return check("launcher", "fail", "no launcher socket: ALT+E starts a slow cold launcher")
    return check("launcher", "ok", "resident launcher ready")


def check_clipboard():
    if not shutil.which("cliphist"):
        return check("clipboard", "info", "cliphist is not installed")
    if not os.access(CLIPHIST_DB, os.R_OK):
        return check("clipboard", "warn", "no clipboard history store yet")
    return check("clipboard", "ok", f"history store {os.path.getsize(CLIPHIST_DB) // 1024} KiB")


def check_disks():
    out, seen = [], set()
    for path in ("/", HOME):
        try:
            st = os.statvfs(path)
        except OSError:
            continue
        key = (st.f_blocks, st.f_bavail)
        if key in seen:
            continue                # /home on the same btrfs as / (another subvolume)
        seen.add(key)
        free = st.f_bavail / st.f_blocks if st.f_blocks else 1
        gib = st.f_bavail * st.f_frsize / 2 ** 30
        level = "fail" if free < DISK_FAIL else "warn" if free < DISK_WARN else "ok"
        out.append(check("disk", level, f"{path}: {gib:.0f} GiB free ({free:.0%})"))
    return out


def check_journal(units):
    rc, out, _ = sh("journalctl", "--user", "-p", "err", "--since", "-1h", "-o", "json", "--no-pager")
    if rc != 0:
        return check("journal", "info", "journal not readable")
    ours = set(units) | {"hyprland", "Hyprland"}
    counts = {}
    for line in out.splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        who = entry.get("_SYSTEMD_USER_UNIT") or entry.get("SYSLOG_IDENTIFIER") or "?"
        if who in ours or entry.get("SYSLOG_IDENTIFIER") in ours:
            counts[who] = counts.get(who, 0) + 1
    if not counts:
        return check("journal", "ok", "no errors from the desktop in the last hour")
    worst = ", ".join(f"{u} {n}" for u, n in sorted(counts.items(), key=lambda kv: -kv[1])[:4])
    return check("journal", "warn", f"errors in the last hour: {worst}  (logs panel)")


def check_lmstudio():
    try:
        with urllib.request.urlopen("http://127.0.0.1:1234/v1/models", timeout=1) as resp:
            n = len(json.load(resp).get("data", []))
        return check("lm studio", "info", f"server up, {n} models")
    except (OSError, ValueError):
        return check("lm studio", "info", "server not running (starts when a local model is asked)")


def check_dotfiles():
    """None (no line) when desktop.conf names no dotfiles repo with a sync.sh."""
    repo = desktop_conf.dotfiles_repo()
    sync = os.path.join(repo, "sync.sh") if repo else ""
    if not repo:
        return None
    if not os.access(sync, os.X_OK):
        return check("dotfiles", "info", "the dotfiles repo's sync.sh is not executable")
    rc, out, _ = sh(sync, "--check", timeout=20)
    try:
        info = json.loads(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return check("dotfiles", "warn", "sync.sh --check gave no answer")
    parts = [f"{info[k]} {k}" for k in ("drift", "uncommitted", "unpushed") if info.get(k)]
    if parts:
        # Changes not synced yet are normal between syncs (the bar's dotfiles
        # pill shows them); commits that never reached GitHub are not.
        level = "warn" if info.get("unpushed") else "info"
        return check("dotfiles", level, "not backed up yet: " + ", ".join(parts))
    return check("dotfiles", "ok", "home and the repo agree, all pushed")


def not_set_up(text):
    """snapper's answer when it has no "root" config yet: "The config 'root'
    does not exist. Likely snapper is not configured." """
    text = text.lower()
    return "does not exist" in text or "not configured" in text or "unknown config" in text


def check_snapshots():
    if not shutil.which("snapper"):
        return check("snapshots", "info", "snapper is not installed")
    rc, out, err = sh("snapper", "--jsonout", "-c", "root", "list")
    if rc != 0 and not_set_up(err or out):
        # Installed but never set up (no "root" config): a choice still to
        # make, not something broken. Maintenance offers the one root step.
        return check("snapshots", "info", "snapper is not set up yet (Settings > Maintenance has the "
                     "one-time root command)")
    if rc != 0:
        return check("snapshots", "warn", f"snapper list failed: {(err or out).strip()[:100]}")
    try:
        snaps = json.loads(out).get("root", [])
        dates = [s["date"] for s in snaps if s.get("date")]
    except (ValueError, AttributeError, KeyError):
        return check("snapshots", "warn", "snapper answered something unreadable")
    if not dates:
        return check("snapshots", "warn", "no snapshots yet")
    newest = max(dates)
    try:
        age = time.time() - time.mktime(time.strptime(newest[:19], "%Y-%m-%d %H:%M:%S"))
    except ValueError:
        return check("snapshots", "ok", f"newest {newest}")
    level = "warn" if age > SNAPSHOT_MAX_AGE else "ok"
    return check("snapshots", level, f"{len(dates)} snapshots, newest {age / 3600:.0f} h ago")


def check_health(light):
    """The last nightly checkup's lines (health.py doctor_checks: a file read,
    no checkup run). Not light: also its worst findings, explained."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("health", os.path.join(os.path.dirname(
            os.path.abspath(__file__)), "health.py"))
        health = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(health)
        return health.doctor_checks(light)
    except Exception as exc:        # noqa: BLE001 - the checkup is extra, never what breaks doctor
        return [check("health", "info", f"no checkup report ({exc})")]


def check_backup():
    """backup.py's last run (a file read, no restic call): None (no line)
    when no backup is set up."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("backup", os.path.join(HERE, "backup.py"))
        backup = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backup)
        found = backup.doctor_check()
    except Exception as exc:        # noqa: BLE001 - backups are extra, never what breaks doctor
        return check("backup", "info", f"backup status unreadable ({exc})")
    return check("backup", *found) if found else None


def run_checks(light=False, health=True):
    """light: the bar's every-minute run -- skips the slow, informational
    ones (LM Studio, the dotfiles rsync dry run). health: the last nightly
    checkup's lines (health.py, which runs these checks itself, says False)."""
    units = check_units()
    out = units + [check_hyprland(), check_screen(), check_launcher(), check_clipboard()]
    out += check_disks()
    out += [check_journal(wanted_units()), check_snapshots()]
    out += [c for c in (check_backup(),) if c]
    if health:
        out += check_health(light)
    if not light:
        out += [c for c in (check_lmstudio(), check_dotfiles()) if c]
    out.sort(key=lambda c: -LEVELS[c["level"]])
    return out


def worst(checks):
    level = max((LEVELS[c["level"]] for c in checks), default=0)
    return {0: "ok", 1: "warn", 2: "fail"}[level]


def fix():
    restarted = []
    for c in run_checks():
        if c["name"] == "units" and c["level"] == "fail" and c.get("unit"):
            sh("systemctl", "--user", "reset-failed", c["unit"])
            rc, _, err = sh("systemctl", "--user", "restart", c["unit"], timeout=30)
            restarted.append(c["unit"])
            desklog.log("doctor", f"restarted {c['unit']}" + (f": {err.strip()}" if rc else ""),
                        "notice" if rc == 0 else "error")
    return restarted


def report(checks):
    mark = {"ok": "  ok ", "info": "  -- ", "warn": " WARN", "fail": " FAIL"}
    lines = [f"{mark[c['level']]}  {c['name']:<10} {c['text']}" for c in checks]
    w = worst(checks)
    lines.append("")
    lines.append({"ok": "All good.", "warn": "Mostly fine; see WARN above.",
                  "fail": "Something is broken; `doctor.py --fix` restarts failed units."}[w])
    return "\n".join(lines)


def bar(checks):
    bad = [c for c in checks if c["level"] in ("warn", "fail")]
    if not bad:
        return {"text": "", "tooltip": "Desktop health: all good", "class": "ok"}
    tip = "\n".join(f"{c['level'].upper()}  {c['text']}" for c in bad[:12])
    return {"text": f"{ICON} {len(bad)}", "tooltip": tip, "class": worst(checks)}


def main(argv):
    if argv[:1] == ["bar"]:
        print(json.dumps(bar(run_checks(light=True))))
    elif argv[:1] == ["--json"]:
        checks = run_checks()
        print(json.dumps({"worst": worst(checks), "checks": checks}, indent=1))
    elif argv[:1] == ["--fix"]:
        done = fix()
        print(f"restarted: {', '.join(done)}" if done else "nothing to restart")
        print(report(run_checks()))
    elif not argv:
        checks = run_checks()
        print(report(checks))
        sys.exit(LEVELS[worst(checks)])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
