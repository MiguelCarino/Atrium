#!/usr/bin/env python3
"""LM Studio inside limits: how much RAM and CPU the local models may take,
and whether they give way to the desktop. Settings > AI & models sets them.

LM Studio's daemon is llmster (~/.lmstudio/llmster/<version>/llmster); each
loaded model is a llama-server it starts as its child. Left to itself, the
daemon is started by whichever program first runs `lms`, so it ends up in
that program's cgroup, where no limit can be put. lmstudio.service (a user
unit in ~/.config/systemd/user) runs it instead, in the foreground -- llmster
does not fork away: `lms` itself starts it the same way, detached, and the
pid it runs as is the one in ~/.lmstudio/.internal/llmster-pid.lock -- so
the llama-servers are in the unit's cgroup too, and the limits hold for all
of them. The unit is not started at login: llm_models.ensure_local (the
launcher, llm-chat, `llm-gpu.py load`) starts it when a local model is
asked for.

The settings, in ~/.local/state/hypr/llm.json next to the model roles:

    ram_limit_gb      GB the daemon and its models may hold together
                      (MemoryMax): past it the unit's own OOM killer ends
                      the model, and the rest of the desktop does not freeze
                      while the kernel looks for something to kill. 0 = no
                      limit. Unset: half of this machine's RAM.
    cpu_limit_pct     a share of ALL the cores (CPUQuota): 50 is half the
                      machine (12 of 24 threads). 0 = no limit. Unset: 50.
    llm_low_priority  true: CPUWeight 20, IOWeight 20 and Nice 10, so the
                      desktop wins whenever both want the CPU or the disk.
                      Unset: true.

Swap is always off for it (MemorySwapMax=0): a model pushed to swap answers
a word a minute, ending it is kinder. MemoryHigh (throttling instead of a
hard stop) is not used: llama-server mlocks its weights when it may, and a
throttled cgroup that cannot give memory back only stalls. (The user
manager's 8 MB memlock limit means it cannot today: its weights are then
ordinary pages, and file cache in the cgroup is dropped before anything is
killed.)

`apply` writes lmstudio.service.d/limits.conf (so the next start has them)
and, when the unit is running, sets the same with `systemctl --user
set-property --runtime` (MemoryMax, CPUQuota and the weights change live).
Nice cannot change on a running service: turning low priority on renices
the running processes' threads to 10; turning it off takes effect when LM
Studio next starts (an unprivileged process cannot raise its priority).

A daemon running OUTSIDE the unit (started by the LM Studio app, or by a
terminal `lms`) is never stopped behind your back: the status says so, and
`adopt` restarts it under the unit -- refused while a model is answering;
the models are unloaded (they load again the next time they are asked for).

    llm-limits.py status [--json]   the limits, and LM Studio's memory and
                                    CPU use against them, inside or outside
    llm-limits.py set KEY VALUE     one setting (checked), then `apply`
    llm-limits.py apply             the drop-in written, the live unit set
    llm-limits.py adopt             a daemon running outside the unit
                                    restarted inside it
    llm-limits.py run               the unit's ExecStart: the newest
                                    installed llmster, exec'd
    llm-limits.py wait              the unit's ExecStartPost: until `lms`
                                    can talk to the daemon (60 s at most)

No GTK here: llm_models imports this.
"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import llm_models  # noqa: E402

HOME = os.path.expanduser("~")
UNIT = "lmstudio.service"
CONFIG = os.environ.get("XDG_CONFIG_HOME") or os.path.join(HOME, ".config")
UNIT_FILE = os.path.join(CONFIG, "systemd", "user", UNIT)
DROPIN = os.path.join(CONFIG, "systemd", "user", UNIT + ".d", "limits.conf")
LLMSTER_ROOT = os.path.join(HOME, ".lmstudio", "llmster")
INSTALL_LOCATION = os.path.join(HOME, ".lmstudio", ".internal", "llmster-install-location.json")
CGROUP_ROOT = "/sys/fs/cgroup"
PROC = "/proc"
KEYS = ("ram_limit_gb", "cpu_limit_pct", "llm_low_priority")
DAEMONS = ("llmster", "lm-studio", "LM Studio")     # /proc comm: the daemon, the app
MODEL_PROC = "llama-server"
# The ports lms looks for the daemon on (its apiServerPorts), in its order.
DAEMON_PORTS = (41343, 52993, 16141, 39414, 22931)
MIN_RAM_GB = 2
MIN_CPU_PCT = 5
LOW_WEIGHT, LOW_NICE = 20, 10
GIB = 1024 ** 3
OUTSIDE = ("LM Studio is running outside the limits (started by the app or a terminal `lms`): "
           "`llm-limits.py adopt`, or Restart under the limits in Settings > AI & models")


# -- the machine and the settings -------------------------------------------------
def machine(meminfo="/proc/meminfo"):
    """{"ram_gb": total RAM in GB (GiB, as free -g), "cpus": threads}."""
    total = 0
    try:
        with open(meminfo) as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    total = int(line.split()[1]) * 1024
                    break
    except (OSError, ValueError, IndexError):
        pass
    return {"ram_gb": round(total / GIB, 1), "cpus": os.cpu_count() or 1}


def defaults(mach=None):
    """What an unset key means: half the RAM (whole GB), half the cores,
    low priority on."""
    mach = mach or machine()
    return {"ram_limit_gb": max(MIN_RAM_GB, round(mach["ram_gb"] / 2)) if mach["ram_gb"] else 0,
            "cpu_limit_pct": 50, "llm_low_priority": True}


def _number(n):
    """16.0 -> 16, 15.5 stays: how a GB figure is stored and shown."""
    return int(n) if float(n).is_integer() else n


def validate(key, value, mach=None):
    """`value` (text from the command line, or already a number / bool) as
    stored, or ValueError saying why not."""
    mach = mach or machine()
    text = str(value).strip().lower()
    if key == "ram_limit_gb":
        if text in ("off", "none", "no"):
            return 0
        try:
            n = round(float(text) * 2) / 2         # half-GB steps
        except ValueError:
            raise ValueError(f"ram_limit_gb is a number of GB, or 0 for no limit (not {value!r})") from None
        top = int(mach["ram_gb"]) or 1024
        if n != 0 and not MIN_RAM_GB <= n <= top:
            raise ValueError(f"ram_limit_gb is {MIN_RAM_GB} to {top} GB (this machine's RAM), or 0 for no limit")
        return _number(n)
    if key == "cpu_limit_pct":
        if text in ("off", "none", "no"):
            return 0
        try:
            n = int(round(float(text.rstrip("%"))))
        except ValueError:
            raise ValueError(f"cpu_limit_pct is a percent of all the cores, or 0 for no limit (not {value!r})") \
                from None
        if n != 0 and not MIN_CPU_PCT <= n <= 100:
            raise ValueError(f"cpu_limit_pct is {MIN_CPU_PCT} to 100 (% of all the cores), or 0 for no limit")
        return n
    if key == "llm_low_priority":
        if text in ("on", "true", "yes", "1"):
            return True
        if text in ("off", "false", "no", "0"):
            return False
        raise ValueError("llm_low_priority is on or off")
    raise ValueError(f"no setting {key!r}")


def limits(data=None, mach=None):
    """The three settings in effect: llm.json's, each one checked, and the
    default for one unset or broken."""
    mach = mach or machine()
    data = llm_models._raw_settings() if data is None else data
    out = defaults(mach)
    for key in KEYS:
        if key in data and data[key] is not None:
            try:
                out[key] = validate(key, data[key], mach)
            except ValueError:
                pass
    return out


# -- the drop-in -------------------------------------------------------------------------
def properties(lim, cpus):
    """[(name, value)] for the unit, in the drop-in's order."""
    low = lim["llm_low_priority"]
    ram = lim["ram_limit_gb"]
    if not ram:
        mem = "infinity"
    elif float(ram).is_integer():
        mem = f"{int(ram)}G"
    else:
        mem = f"{int(ram * 1024)}M"
    quota = f"{lim['cpu_limit_pct'] * cpus}%" if lim["cpu_limit_pct"] else ""
    return [("MemoryMax", mem), ("MemorySwapMax", "0"), ("CPUQuota", quota),
            ("CPUWeight", str(LOW_WEIGHT if low else 100)), ("IOWeight", str(LOW_WEIGHT if low else 100)),
            ("Nice", str(LOW_NICE if low else 0))]


def render_dropin(lim, cpus):
    """limits.conf's text for these limits on a machine with `cpus` threads."""
    ram = f"{lim['ram_limit_gb']} GB" if lim["ram_limit_gb"] else "no limit"
    cpu = f"{lim['cpu_limit_pct']} % of all {cpus} threads" if lim["cpu_limit_pct"] else "no limit"
    lines = ["# Written by ~/.config/hypr/scripts/llm-limits.py from ~/.local/state/hypr/llm.json",
             "# (Settings > AI & models): edits here are overwritten the next time it applies.",
             f"# RAM {ram}, CPU {cpu}, low priority {'on' if lim['llm_low_priority'] else 'off'}.",
             "[Service]"]
    lines += [f"{name}={value}" for name, value in properties(lim, cpus)]
    return "\n".join(lines) + "\n"


def _systemctl(*args, timeout=20):
    return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, timeout=timeout)


def unit_installed():
    return os.path.isfile(UNIT_FILE)


def write_dropin(lim=None, mach=None):
    """limits.conf as the settings say; True when it changed (systemd is then
    told to read it again)."""
    mach = mach or machine()
    text = render_dropin(lim or limits(mach=mach), mach["cpus"])
    try:
        with open(DROPIN) as handle:
            if handle.read() == text:
                return False
    except OSError:
        pass
    os.makedirs(os.path.dirname(DROPIN), exist_ok=True)
    tmp = DROPIN + ".tmp"
    with open(tmp, "w") as handle:
        handle.write(text)
    os.replace(tmp, DROPIN)
    try:
        _systemctl("daemon-reload", timeout=30)
    except (OSError, subprocess.SubprocessError):
        pass
    return True


def unit_active():
    try:
        return _systemctl("is-active", UNIT, timeout=5).stdout.strip() in ("active", "activating", "reloading")
    except (OSError, subprocess.SubprocessError):
        return False


def apply():
    """The drop-in written and, while the unit runs, the same set live.
    Returns the lines to show."""
    mach = machine()
    lim = limits(mach=mach)
    out = []
    if write_dropin(lim, mach):
        out.append(f"wrote {DROPIN.replace(HOME, '~')}")
    if not unit_installed():
        out.append(f"{UNIT} is not installed: the limits hold once it is")
        return out
    if not unit_active():
        out.append("LM Studio is not running under the limits now: they hold from its next start")
        return out
    live = [f"{n}={v}" for n, v in properties(lim, mach["cpus"]) if n != "Nice"]
    r = _systemctl("set-property", "--runtime", UNIT, *live)
    out.append("set live: " + " ".join(live) if r.returncode == 0 else
               "set-property failed: " + (r.stderr or r.stdout).strip()[-200:])
    want = LOW_NICE if lim["llm_low_priority"] else 0
    pids = cgroup_pids()
    if want and pids:
        n = renice(pids, want)
        if n:
            out.append(f"reniced {n} threads to {want}")
    elif not want and any(nice_of(p) > 0 for p in pids):
        out.append("normal priority takes effect when LM Studio next starts (a running process cannot "
                   "raise its own priority)")
    return out


def renice(pids, nice):
    """Every thread of `pids` to at least `nice` (never lower: that needs
    privileges). Returns how many were changed."""
    n = 0
    for pid in pids:
        try:
            tids = os.listdir(f"{PROC}/{pid}/task")
        except OSError:
            continue
        for tid in tids:
            try:
                if os.getpriority(os.PRIO_PROCESS, int(tid)) < nice:
                    os.setpriority(os.PRIO_PROCESS, int(tid), nice)
                    n += 1
            except (OSError, ValueError):
                pass
    return n


def nice_of(pid):
    try:
        with open(f"{PROC}/{pid}/stat") as handle:
            return int(handle.read().rsplit(")", 1)[1].split()[16])
    except (OSError, ValueError, IndexError):
        return 0


def set_limit(key, value):
    """`set KEY VALUE`: checked, saved, applied. The lines to show."""
    llm_models.save_setting(key, validate(key, value))
    return apply()


# -- where LM Studio runs ------------------------------------------------------------
def cgroup_dir():
    """The unit's cgroup folder under /sys/fs/cgroup, or None while it is
    not running."""
    try:
        path = _systemctl("show", "-p", "ControlGroup", "--value", UNIT, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return os.path.join(CGROUP_ROOT, path.lstrip("/")) if path else None


def cgroup_pids(cg=None):
    cg = cg or cgroup_dir()
    if not cg:
        return []
    try:
        with open(os.path.join(cg, "cgroup.procs")) as handle:
            return [int(p) for p in handle.read().split()]
    except (OSError, ValueError):
        return []


def lm_procs(proc=None):
    """[{pid, comm, cgroup}] of LM Studio's processes (the daemon or the
    app, and llama-servers), from /proc (asking lms would wake it)."""
    proc = proc or PROC
    out = []
    try:
        pids = [p for p in os.listdir(proc) if p.isdigit()]
    except OSError:
        return out
    for pid in pids:
        try:
            with open(f"{proc}/{pid}/comm") as handle:
                comm = handle.read().strip()
            if comm not in DAEMONS and comm != MODEL_PROC:
                continue
            with open(f"{proc}/{pid}/cgroup") as handle:
                group = next((line.split("::", 1)[1].strip() for line in handle if line.startswith("0::")), "")
        except OSError:
            continue
        out.append({"pid": int(pid), "comm": comm, "cgroup": group})
    return out


def in_unit(group):
    return group.endswith("/" + UNIT) or ("/" + UNIT + "/") in group


def placement(procs):
    """"none" (no daemon), "inside" (it runs in the unit) or "outside"."""
    daemons = [p for p in procs if p["comm"] in DAEMONS]
    if not daemons:
        return "none"
    return "inside" if all(in_unit(p["cgroup"]) for p in daemons) else "outside"


def daemon_ready():
    """Does the daemon answer lms (its /lms-status) on one of lms's ports?"""
    for port in DAEMON_PORTS:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/lms-status", timeout=1) as r:
                if r.status == 200 and "package" in json.loads(r.read() or b"{}"):
                    return True
        except (OSError, ValueError):
            continue
    return False


def wait_ready(timeout=60):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if daemon_ready():
            return True
        time.sleep(0.5)
    return False


def ensure_daemon(status=lambda text: None):
    """Before ensure_local talks to lms: the daemon started under the unit
    when it is not running. Returns a line for the caller to show ("" when
    all is as it should be): it runs outside the limits, or the unit would
    not start (lms then starts it the old way). Without the unit file,
    nothing is done (the old way)."""
    if not unit_installed():
        return ""
    where = placement(lm_procs())
    if where == "inside":
        return ""
    if where == "outside":
        status(OUTSIDE)
        return OUTSIDE
    status("starting LM Studio (inside the limits)…")
    try:
        write_dropin()
        r = _systemctl("start", UNIT, timeout=150)
        ok = r.returncode == 0 and wait_ready(10)
        why = (r.stderr or r.stdout).strip()[-200:] if r.returncode else "it did not answer"
    except (OSError, subprocess.SubprocessError) as exc:
        ok, why = False, str(exc)
    if ok:
        return ""
    note = f"{UNIT} did not start ({why}): LM Studio is started the old way, outside the limits"
    status(note)
    return note


# -- what the limit did -------------------------------------------------------------------
def oom_kills(cg=None):
    """memory.events' oom_kill for the unit's cgroup: how many processes its
    own OOM killer ended since it started; None while it is not running."""
    cg = cg or cgroup_dir()
    if not cg:
        return None
    try:
        with open(os.path.join(cg, "memory.events")) as handle:
            for line in handle:
                name, _, value = line.partition(" ")
                if name == "oom_kill":
                    return int(value)
    except (OSError, ValueError):
        return None
    return 0


def oom_reason(before, after, name, ram_gb):
    """ensure_local's why for a failed load the limit ended, or ""."""
    if before is None or after is None or after <= before:
        return ""
    return (f"{name} hit LM Studio's RAM limit of {ram_gb} GB and was ended: raise the limit in "
            "Settings > AI & models, or use a smaller model or context")


# -- status -------------------------------------------------------------------------------
def _read_int(path, key=None):
    try:
        with open(path) as handle:
            if key is None:
                text = handle.read().strip()
                return None if text == "max" else int(text)
            for line in handle:
                k, _, v = line.partition(" ")
                if k == key:
                    return int(v)
    except (OSError, ValueError):
        pass
    return None


def _rss(pid):
    try:
        with open(f"{PROC}/{pid}/status") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return 0


def _ticks(pids):
    total = 0
    for pid in pids:
        try:
            with open(f"{PROC}/{pid}/stat") as handle:
                fields = handle.read().rsplit(")", 1)[1].split()
            total += int(fields[11]) + int(fields[12])      # utime, stime
        except (OSError, ValueError, IndexError):
            pass
    return total


def usage(cg, pids, sample=0.5, cpus=None):
    """{"current", "own", "peak", "cpu_pct"}: the cgroup's memory (all of it,
    file cache included, as the limit counts it; and the processes' own,
    anon + shared) and its CPU over `sample` seconds as a share of all the
    cores. Without a cgroup (outside the unit), the processes' RSS and CPU."""
    cpus = cpus or os.cpu_count() or 1
    if cg:
        current = _read_int(os.path.join(cg, "memory.current"))
        own = sum(_read_int(os.path.join(cg, "memory.stat"), k) or 0 for k in ("anon", "shmem"))
        peak = _read_int(os.path.join(cg, "memory.peak"))
        t0 = _read_int(os.path.join(cg, "cpu.stat"), "usage_usec")
        time.sleep(sample)
        t1 = _read_int(os.path.join(cg, "cpu.stat"), "usage_usec")
        cpu = (t1 - t0) / 1e6 / sample / cpus * 100 if t0 is not None and t1 is not None else None
        return {"current": current, "own": own, "peak": peak, "cpu_pct": cpu}
    hz = os.sysconf("SC_CLK_TCK")
    t0 = _ticks(pids)
    time.sleep(sample)
    t1 = _ticks(pids)
    rss = sum(_rss(p) for p in pids)
    return {"current": rss, "own": rss, "peak": None, "cpu_pct": (t1 - t0) / hz / sample / cpus * 100}


def status(sample=0.5):
    mach = machine()
    lim = limits(mach=mach)
    procs = lm_procs()
    where = placement(procs)
    active = unit_active() if unit_installed() else False
    cg = cgroup_dir() if active else None
    pids = [p["pid"] for p in procs]
    use = usage(cg if where == "inside" else None, pids, sample, mach["cpus"]) if procs else {}
    daemon = next((p for p in procs if p["comm"] in DAEMONS), None)
    try:
        with open(DROPIN) as handle:
            written = handle.read() == render_dropin(lim, mach["cpus"])
    except OSError:
        written = False
    return {"machine": mach, "limits": lim, "defaults": defaults(mach), "unit": unit_installed(),
            "active": active, "where": where, "app": bool(daemon and daemon["comm"] != "llmster"),
            "outside_pids": [p["pid"] for p in procs if not in_unit(p["cgroup"])] if where == "outside" else [],
            "usage": use, "oom_kills": oom_kills(cg) if cg else None,
            "nice": nice_of(daemon["pid"]) if daemon else None, "dropin": written}


def gb(n):
    return f"{(n or 0) / GIB:.1f} GB"


def status_lines(s):
    lim, mach = s["limits"], s["machine"]
    out = [f"limits: RAM {str(lim['ram_limit_gb']) + ' GB' if lim['ram_limit_gb'] else 'none'} of "
           f"{mach['ram_gb']} GB, CPU {str(lim['cpu_limit_pct']) + ' %' if lim['cpu_limit_pct'] else 'none'} "
           f"of {mach['cpus']} threads, low priority {'on' if lim['llm_low_priority'] else 'off'}"]
    if not s["unit"]:
        out.append(f"{UNIT} is not installed: LM Studio runs the old way, with no limits")
    where = {"none": "LM Studio is not running", "inside": f"LM Studio is running inside the limits ({UNIT})",
             "outside": "LM Studio is running OUTSIDE the limits"
                        + (" (the app runs it: quit the app first)" if s["app"] else ": llm-limits.py adopt")}
    out.append(where[s["where"]])
    use = s["usage"]
    if use:
        line = f"memory {gb(use['current'])}"
        if s["where"] == "inside":
            line += f" (its own {gb(use['own'])}, the rest file cache)"
            if lim["ram_limit_gb"]:
                line += f" of {lim['ram_limit_gb']} GB"
            if use.get("peak"):
                line += f", peak {gb(use['peak'])}"
        if use.get("cpu_pct") is not None:
            line += f"; CPU {use['cpu_pct']:.0f} % of the machine"
        out.append(line)
    if s.get("oom_kills"):
        out.append(f"the RAM limit has ended {s['oom_kills']} process(es) since LM Studio started")
    if s["where"] == "inside" and lim["llm_low_priority"] and (s["nice"] or 0) < LOW_NICE:
        out.append("low priority: the weights hold now, nice 10 from the next start (or llm-limits.py apply)")
    return out


# -- adopt, run, wait -----------------------------------------------------------------------
def adopt():
    """A daemon running outside the unit stopped (`lms daemon down`) and
    started again inside it. Refused while a model is answering, or while
    the LM Studio app runs it (quit the app: lms cannot stop it). The lines
    to show; RuntimeError when refused."""
    if not unit_installed():
        raise RuntimeError(f"{UNIT} is not installed")
    procs = lm_procs()
    where = placement(procs)
    if where == "inside":
        return ["LM Studio is running inside the limits already"]
    out = []
    if where == "outside":
        if any(p["comm"] in DAEMONS and p["comm"] != "llmster" for p in procs):
            raise RuntimeError("the LM Studio app runs the daemon: quit the app, then start a local model")
        try:
            loaded = llm_models._json_out(llm_models._lms("ps", "--json").stdout) or []
        except (OSError, subprocess.SubprocessError, ValueError):
            loaded = []
        busy = [m.get("identifier") or m.get("modelKey") for m in loaded if isinstance(m, dict)
                and (m.get("status") not in (None, "idle") or m.get("queued"))]
        if busy:
            raise RuntimeError(f"{', '.join(busy)} is answering now: try again when it is idle")
        names = [m.get("identifier") or m.get("modelKey") for m in loaded if isinstance(m, dict)]
        r = llm_models._lms("daemon", "down", timeout=40)
        if r.returncode:
            raise RuntimeError("lms daemon down failed: " + (r.stderr or r.stdout).strip()[-200:])
        end = time.monotonic() + 30
        while time.monotonic() < end and any(p["pid"] for p in lm_procs() if not in_unit(p["cgroup"])):
            time.sleep(0.5)
        left = [p for p in lm_procs() if not in_unit(p["cgroup"])]
        if left:
            raise RuntimeError("LM Studio did not stop (pids " + ", ".join(str(p["pid"]) for p in left) + ")")
        out.append("stopped LM Studio" + (f" (unloaded {', '.join(names)}: they load again when asked for)"
                                          if names else ""))
    write_dropin()
    r = _systemctl("start", UNIT, timeout=150)
    if r.returncode or not wait_ready(10):
        raise RuntimeError(f"{UNIT} did not start: " + ((r.stderr or r.stdout).strip()[-200:] or "no answer")
                           + "; LM Studio starts the old way the next time a model is asked for")
    out.append(f"LM Studio is running inside the limits ({UNIT})")
    return out


def _version_key(name):
    return [int(p) if p.isdigit() else p for p in re.split(r"[.\-]", name)]


def newest_llmster(root=None):
    """The newest installed llmster binary (~/.lmstudio/llmster/<version>/),
    so an update does not break the unit; else the one lms recorded."""
    root = root or LLMSTER_ROOT
    found = []
    try:
        for entry in os.scandir(root):
            exe = os.path.join(entry.path, "llmster")
            if entry.is_dir() and os.access(exe, os.X_OK):
                found.append((_version_key(entry.name), exe))
    except OSError:
        pass
    if found:
        return max(found, key=lambda f: f[0])[1]
    try:
        with open(INSTALL_LOCATION) as handle:
            path = json.load(handle).get("path")
        return path if path and os.access(path, os.X_OK) else None
    except (OSError, ValueError, AttributeError):
        return None


def run():
    """exec llmster the way lms starts it (its own folder as the working
    directory, DISPLAY when unset), in the foreground: the unit's main
    process."""
    exe = newest_llmster()
    if not exe:
        sys.exit(f"llm-limits: no llmster under {LLMSTER_ROOT}")
    os.chdir(os.path.dirname(exe))
    env = dict(os.environ)
    env.setdefault("DISPLAY", ":0")
    os.execve(exe, [exe], env)


def main(argv):
    cmd = argv[0] if argv else "status"
    try:
        if cmd == "status":
            s = status()
            print(json.dumps(s, indent=1) if "--json" in argv else "\n".join(status_lines(s)))
            return 0
        if cmd == "set" and len(argv) == 3:
            print("\n".join(set_limit(argv[1], argv[2])))
            return 0
        if cmd == "apply":
            print("\n".join(apply()))
            return 0
        if cmd == "adopt":
            print("\n".join(adopt()))
            return 0
        if cmd == "run":
            run()
        if cmd == "wait":
            return 0 if wait_ready(float(argv[1]) if len(argv) > 1 else 60) else 1
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"llm-limits: {exc}", file=sys.stderr)
        return 1
    print(__doc__.split("\n\n")[-2], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
