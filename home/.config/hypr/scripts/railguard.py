#!/usr/bin/env python3
"""Railguard: keep the desktop -- and the coding-agent sessions in its
terminals -- alive when something suddenly takes all the RAM, CPU or VRAM.
A freeze costs a reboot and every session's context; ending the one runaway
process costs nothing but that process. Settings > Railguard sets it all.

The layers (each one alone already helps):

    agents.slice      every command a coding agent runs (Claude Code's Bash
                      tool, hooks, MCP servers -- railguard-run is its
                      CLAUDE_CODE_SHELL_PREFIX) gets its own scope there,
                      capped per command and all together, oom_score_adj
                      300. The agent itself stays in the terminal's scope in
                      session.slice, out of reach.
    heavy.slice       what you start by hand that is heavy: `heavy CMD`, and
                      make/ninja/cmake/meson/cargo/rpmbuild typed in a shell
                      (railguard-shell.sh, sourced by ~/.bashrc). Nearly the
                      whole machine when it is idle, lowest priority, so it
                      steps aside for the desktop and a game.
    session.slice     (drop-in) CPUWeight 300, MemoryLow 4G: the compositor,
                      the terminals and the sessions win the CPU and keep
                      their pages when something else runs away.
    app.slice         (drop-in) systemd-oomd ends the stalling app at 60 %
                      memory pressure for 15 s (Fedora's default: 80 %, 20 s).
    this daemon       the cases above react too late for: RAM running out in
                      seconds, and the GPU's memory -- no cgroup limits that.
    SysRq             (Atrium/system/railguard, needs sudo) Alt+SysRq+F runs
                      the kernel's OOM killer even when nothing on screen
                      answers any more; Alt+SysRq+REISUB reboots cleanly.

    railguard.py daemon             the watchdog (railguard.service)
    railguard.py status [--json]    memory, swap, pressure, VRAM, the slices,
                                    the settings, the last actions
    railguard.py history [--json] [-n N]   what it ended, newest first
    railguard.py set KEY VALUE      one setting (SETTINGS below); a limit
                                    is applied at once (apply)
    railguard.py add|remove LIST NAME     never_kill / kill_first
    railguard.py apply              write the limits to the slices
    railguard.py panic              end the worst process now: the biggest
                                    when RAM is short, else the busiest
                                    (SUPER+CTRL+ALT+Escape)
    railguard.py stop-agents        end every command the agents started;
                                    the sessions stay

THE DAEMON, once a second (the GPU every 3 s):

    RAM       MemAvailable under ram_free_pct of RAM while swap is
              swap_used_pct full (or there is none), or memory "full"
              pressure (PSI avg10) over stall_pct for stall_s seconds:
              SIGKILL the biggest killable process (RSS + swap).
    VRAM      vram_pct or more of the GPU's memory for vram_s seconds:
              SIGTERM (SIGKILL 5 s later) the compute process holding the
              most -- never a game while spare_games is on: when the game is
              the one filling it, it only warns (lower the textures), and
              when something else is (a model, a browser tab) that goes, so
              the game keeps running. Processes the driver lists only as
              graphics are not listed with their usage -- then it warns.
    GPU load  not watched: a game at 100 % is the GPU doing its job. When the
              desktop stutters because something else holds the GPU, the
              panic key ends it -- no driver offers a limit for GPU time.
              The card is read in-process (gpu.py: NVML on NVIDIA, sysfs
              and fdinfo on AMD / Intel); with no card that reports its
              memory (an iGPU, none) the VRAM watch is off by itself.

WHO GOES FIRST -- each candidate's size is weighed:

    x4    a name on your kill_first list
    x2    agents.slice and heavy.slice: an agent's command, your build
    x1    everything else (the browser, apps)
    x0.5  session.slice -- programs Hyprland starts live in the
          compositor's own cgroup there -- and games (Steam's SteamAppId,
          Proton's STEAM_COMPAT_APP_ID, Lutris, Heroic)
    never PROTECTED (the compositor, the terminals, their shells, the agent
          sessions: a shell or terminal ended takes its agent with it), your
          never_kill list, anything not yours

After acting it waits 10 s before acting again.

SETTINGS ($XDG_STATE_HOME/hypr/railguard.json, every key optional):

    ram, vram         the two watches on / off (true)
    notify            a notification for each action (true); the mascot's
                      face and voice on it are Settings > Notifications'
                      (mascot_notify.py). Off: the journal and the history only
    ram_free_pct 4, swap_used_pct 80, stall_pct 50, stall_s 5,
    vram_pct 97, vram_s 12
    spare_games       games are never ended for VRAM, and count half (true)
    never_kill        process names it must never end ([])
    kill_first        process names that go first (x4) ([])
    agent_command_gb  one agent command at most (16)
    agents_gb         all agent commands together (20)
    heavy_gb          everything in heavy.slice together (24)
    agents_threads    CPU threads the agents' commands may use (20)
    heavy_threads     and heavy.slice (22)

The limits are written by `apply` as drop-ins (agents.slice.d/limits.conf,
heavy.slice.d/limits.conf; MemoryHigh 2 GB under the cap) and set live with
`systemctl --user set-property --runtime`; the per-command cap is a file
railguard-run reads ($XDG_STATE_HOME/hypr/railguard-command-max).

HISTORY: $XDG_STATE_HOME/hypr/railguard-history.jsonl, one line per action
({"time", "kind", "name", "pid", "unit", "gb", "why"}; kind memory, vram,
game-vram, stuck, panic, agents), the last 500 kept. Settings > Railguard
lists it; brief.py's health section shows the last day's (brief_lines).
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "hypr")
SETTINGS_FILE = os.path.join(STATE_DIR, "railguard.json")
HISTORY_FILE = os.path.join(STATE_DIR, "railguard-history.jsonl")
COMMAND_MAX_FILE = os.path.join(STATE_DIR, "railguard-command-max")
UNIT_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
                        "systemd", "user")
HISTORY_KEEP = 500

SETTINGS = {
    "ram": True, "vram": True, "notify": True,
    "ram_free_pct": 4.0, "swap_used_pct": 80.0, "stall_pct": 50.0, "stall_s": 5,
    "vram_pct": 97.0, "vram_s": 12,
    "spare_games": True, "never_kill": [], "kill_first": [],
    "agent_command_gb": 16, "agents_gb": 20, "heavy_gb": 24,
    "agents_threads": 20, "heavy_threads": 22,
}
LISTS = ("never_kill", "kill_first")
LIMITS = ("agent_command_gb", "agents_gb", "heavy_gb", "agents_threads", "heavy_threads")
# the sane range of each number (Settings offers values inside it)
RANGES = {"ram_free_pct": (1, 20), "swap_used_pct": (0, 100), "stall_pct": (10, 95),
          "stall_s": (1, 60), "vram_pct": (80, 100), "vram_s": (3, 120),
          "agent_command_gb": (1, 64), "agents_gb": (2, 64), "heavy_gb": (2, 64),
          "agents_threads": (1, 64), "heavy_threads": (1, 64)}

TICK = 1.0
GPU_EVERY = 3                 # ticks
COOLDOWN = 10.0
AGENT_WEIGHT = 2.0            # agents.slice / heavy.slice look this much bigger
SESSION_WEIGHT = 0.5          # session.slice ones this much smaller
GAME_WEIGHT = 0.5             # and games
FIRST_WEIGHT = 4.0            # kill_first names
VRAM_MIN_MIB = 512            # below this a process is not worth ending for VRAM

SESSION_SLICE = "/session.slice/"
BATCH_SLICES = ("/agents.slice/", "/heavy.slice/")
GAME_ENV = (b"SteamAppId=", b"STEAM_COMPAT_APP_ID=", b"LUTRIS_GAME_UUID=",
            b"HEROIC_APP_NAME=")
PROTECTED = {
    "Hyprland", "Xwayland", "kitty", "claude", "waybar", "hyprpaper",
    "hypridle", "hyprlock", "mako", "pipewire", "pipewire-pulse",
    "wireplumber", "dbus-broker", "dbus-daemon", "systemd", "uwsm",
    "xdg-desktop-portal", "xdg-desktop-portal-hyprland", "gnome-keyring-d",
    "bash", "zsh", "fish", "sh", "tmux: server", "sshd-session",
}
UID = os.getuid()
ME = os.getpid()
CFG = dict(SETTINGS)          # the settings in effect (load_settings)


def log(msg):
    print(msg, flush=True)


# --- settings and history -------------------------------------------------------

def read_settings():
    cur = json.loads(json.dumps(SETTINGS))
    try:
        with open(SETTINGS_FILE) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {}
    for k, v in (data if isinstance(data, dict) else {}).items():
        if k not in cur:
            continue
        if k in LISTS:
            if isinstance(v, list):
                cur[k] = sorted({str(x) for x in v if str(x).strip()})
        elif isinstance(cur[k], bool):
            cur[k] = bool(v)
        else:
            try:
                lo, hi = RANGES[k]
                cur[k] = type(SETTINGS[k])(min(hi, max(lo, float(v))))
            except (TypeError, ValueError):
                pass
    return cur


def write_settings(cur):
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = SETTINGS_FILE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump({k: cur[k] for k in SETTINGS}, fh, indent=1)
        fh.write("\n")
    os.replace(tmp, SETTINGS_FILE)


def load_settings():
    CFG.clear()
    CFG.update(read_settings())


def record(kind, p=None, why="", **extra):
    entry = {"time": int(time.time()), "kind": kind, "why": why}
    if p:
        entry.update(name=p["name"], pid=p["pid"], unit=unit_of(p),
                     gb=round(p.get("mem", 0) / 1024 ** 3, 1))
    entry.update(extra)
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(HISTORY_FILE, "a") as fh:
            fh.write(json.dumps(entry) + "\n")
        with open(HISTORY_FILE) as fh:
            lines = fh.readlines()
        if len(lines) > 2 * HISTORY_KEEP:
            tmp = HISTORY_FILE + ".tmp"
            with open(tmp, "w") as fh:
                fh.writelines(lines[-HISTORY_KEEP:])
            os.replace(tmp, HISTORY_FILE)
    except OSError as exc:
        log(f"history not kept: {exc}")


def history(n=50, since=None):
    try:
        with open(HISTORY_FILE) as fh:
            lines = fh.readlines()
    except OSError:
        return []
    out = []
    for line in reversed(lines):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if since and e.get("time", 0) < since:
            break
        out.append(e)
        if len(out) >= n:
            break
    return out


def brief_lines(now=None):
    """The morning brief's lines (brief.py's health section): what railguard
    did in the last 24 h, [] when nothing."""
    now = now if now is not None else time.time()
    got = [e for e in history(200, since=now - 86400) if e.get("kind") != "agents"]
    if not got:
        return []
    ended = [e for e in got if e["kind"] in ("memory", "vram", "panic")]
    lines = [f"Railguard: {len(ended)} runaway{'s' if len(ended) != 1 else ''} ended in the last day"
             + (f", {len(got) - len(ended)} warning{'s' if len(got) - len(ended) != 1 else ''}"
                if len(got) > len(ended) else "") + " (Settings > Railguard)"]
    for e in got[:3]:
        lines.append(describe(e))
    return lines


def notify(title, body, mood="alert", say=None):
    """A notification through mascot_notify (the theme's mascot as the icon,
    its voice when that is on), and always the journal and the dynamic
    island (island_events.py; nothing when the island is off)."""
    log(f"{title}: {body}")
    try:                    # the dynamic island, even with notifications off
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        import island_events
        island_events.railguard(title, body, mood)
    except Exception:
        pass
    if not CFG["notify"] or not shutil.which("notify-send"):
        return
    try:
        sys.path.insert(0, HERE)
        import mascot_notify
        mascot_notify.send(title, body, app="Railguard", urgency="critical",
                           mood=mood, say=say)
    except Exception as exc:
        log(f"mascot_notify failed ({exc}); plain notify-send")
        subprocess.Popen(["notify-send", "-u", "critical", "-a", "Railguard", title, body],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# --- reading the machine ---------------------------------------------------

def meminfo():
    m = {}
    with open("/proc/meminfo") as f:
        for line in f:
            k, v = line.split(":", 1)
            m[k] = int(v.split()[0]) * 1024
    return m


def psi_full_avg10(res="memory"):
    try:
        with open(f"/proc/pressure/{res}") as f:
            for line in f:
                if line.startswith("full"):
                    return float(line.split()[1].split("=")[1])
    except OSError:
        pass
    return 0.0


# The card comes from gpu.py, in-process: NVML through ctypes on NVIDIA (no
# nvidia-smi started every 3 s -- that fork was nearly all of this daemon's
# CPU), amdgpu's sysfs and fdinfo on AMD, fdinfo on an Intel card with memory
# of its own. A card that reports no memory (an iGPU, nouveau, no card at
# all) turns the VRAM watch off by itself: gpu_memory() is None.
GPU = None          # the gpu.py module once loaded, False when it would not load


def _gpu():
    global GPU
    if GPU is None:
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        try:
            import gpu as module
        except Exception as exc:  # noqa: BLE001  (a broken gpu.py must not stop the RAM watch)
            log(f"gpu.py failed to load ({exc}); VRAM not watched")
            module = False
        GPU = module
    return GPU or None


def gpu_card():
    """The main card when it has memory of its own and reports it
    (gpu.primary()), else None. An integrated GPU's "VRAM" is a carve-out of
    the RAM that fills up as a matter of course (the driver spills into
    system memory): nothing to guard there."""
    mod = _gpu()
    if mod is None:
        return None
    try:
        card = mod.primary()
    except Exception as exc:  # noqa: BLE001
        log(f"gpu.py: {exc}")
        return None
    return card if (card and card.get("discrete", True) and card.get("vram_total")
                    and card.get("vram_used") is not None) else None


def gpu_memory(card=None):
    """(used MiB, total MiB) of the main GPU, or None."""
    card = card or gpu_card()
    return (card["vram_used"], card["vram_total"]) if card else None


def gpu_processes(card=None):
    """{pid: MiB} on the main GPU: the compute processes only (graphics ones
    -- the compositor, a game, a browser's drawing -- are not candidates):
    NVIDIA's compute list, AMD's ROCm clients (/dev/kfd); none on a card
    that cannot tell the two apart (gpu.processes compute_only)."""
    card = card or gpu_card()
    mod = _gpu()
    if not card or mod is None:
        return {}
    try:
        return mod.processes(card, compute_only=True)
    except Exception as exc:  # noqa: BLE001
        log(f"gpu.py: {exc}")
        return {}


def is_game(pid):
    try:
        with open(f"/proc/{pid}/environ", "rb") as f:
            env = f.read()
    except OSError:
        return False
    return any(env.startswith(k) or b"\0" + k in env for k in GAME_ENV)


def proc_info(pid):
    """name, cgroup, rss+swap bytes, cpu ticks, weight, game -- or None when
    it is gone or not killable."""
    try:
        if os.stat(f"/proc/{pid}").st_uid != UID or pid == ME:
            return None
        with open(f"/proc/{pid}/cgroup") as f:
            cgroup = f.read().strip().split("::", 1)[-1]
        with open(f"/proc/{pid}/stat") as f:
            stat = f.read()
        name = stat[stat.index("(") + 1:stat.rindex(")")]
        fields = stat[stat.rindex(")") + 2:].split()
        ticks = int(fields[11]) + int(fields[12])
        mem = 0
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith(("VmRSS:", "VmSwap:")):
                    mem += int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    if name in PROTECTED or name in CFG["never_kill"] or "user@" not in cgroup:
        return None
    game = is_game(pid)
    weight = (FIRST_WEIGHT if name in CFG["kill_first"]
              else AGENT_WEIGHT if any(s in cgroup for s in BATCH_SLICES)
              else GAME_WEIGHT if game and CFG["spare_games"]
              else SESSION_WEIGHT if SESSION_SLICE in cgroup else 1.0)
    return {"pid": pid, "name": name, "cgroup": cgroup, "mem": mem,
            "ticks": ticks, "weight": weight, "game": game}


def killable():
    out = []
    for d in os.listdir("/proc"):
        if d.isdigit():
            p = proc_info(int(d))
            if p:
                out.append(p)
    return out


def biggest():
    procs = killable()
    if not procs:
        return None
    return max(procs, key=lambda p: p["mem"] * p["weight"])


def busiest(sample=1.0):
    before = {p["pid"]: p for p in killable()}
    time.sleep(sample)
    best, best_d = None, 0
    for pid, p in before.items():
        now = proc_info(pid)
        d = (now["ticks"] - p["ticks"]) * now["weight"] if now else 0
        if d > best_d:
            best, best_d = now, d
    if best:
        best["cpu_pct"] = (100.0 * (best["ticks"] - before[best["pid"]]["ticks"])
                           / os.sysconf("SC_CLK_TCK") / sample)
    return best


def unit_of(p):
    return p["cgroup"].rstrip("/").rsplit("/", 1)[-1]


def where(p):
    return f"{p['name']} (pid {p['pid']}, {unit_of(p)})"


def gib(n):
    return f"{n / 1024 ** 3:.1f} GB"


def kill(p, sig=signal.SIGKILL):
    try:
        os.kill(p["pid"], sig)
        return True
    except OSError:
        return False


def term_then_kill(p, wait=5.0):
    if not kill(p, signal.SIGTERM):
        return False
    end = time.time() + wait
    while time.time() < end:
        if not os.path.exists(f"/proc/{p['pid']}"):
            return True
        time.sleep(0.25)
    kill(p)
    return True


# --- the watch -----------------------------------------------------------------

def check_ram(state, now):
    m = meminfo()
    avail_pct = 100.0 * m["MemAvailable"] / m["MemTotal"]
    swap_total = m.get("SwapTotal", 0)
    swap_used_pct = (100.0 * (swap_total - m.get("SwapFree", 0)) / swap_total
                     if swap_total else 100.0)
    state["psi"] = state["psi"] + 1 if psi_full_avg10() > CFG["stall_pct"] else 0
    low = avail_pct < CFG["ram_free_pct"] and swap_used_pct > CFG["swap_used_pct"]
    if not (low or state["psi"] >= CFG["stall_s"]) or now < state["quiet"]:
        return
    p = biggest()
    why = (f"{avail_pct:.1f}% RAM free, swap {swap_used_pct:.0f}% used"
           if low else f"memory stalled {state['psi']}s")
    if p and kill(p):
        record("memory", p, why)
        notify("Railguard ended a memory runaway",
               f"{where(p)} held {gib(p['mem'])} -- {why}.",
               mood="relieved", say=("rg_memory", p["name"]))
    else:
        record("stuck", None, why)
        notify("Railguard: memory is running out",
               f"{why}, and nothing it may end was found.", say=("rg_stuck",))
    state["quiet"], state["psi"] = now + COOLDOWN, 0


def check_vram(state):
    card = gpu_card()
    g = gpu_memory(card)
    vram_pct = 100.0 * g[0] / g[1] if g else 0.0
    state["vram"] = state["vram"] + 1 if vram_pct >= CFG["vram_pct"] else 0
    if state["vram"] * GPU_EVERY < CFG["vram_s"] or time.time() < state["quiet"]:
        return
    cands = [(mib, proc_info(pid)) for pid, mib in gpu_processes(card).items()]
    cands = [(mib, p) for mib, p in cands if p]
    spare = CFG["spare_games"]
    others = [c for c in cands if not (spare and c[1]["game"]) and c[0] >= VRAM_MIN_MIB]
    games = [c for c in cands if spare and c[1]["game"]]
    quiet = COOLDOWN * 3
    if others:
        mib, p = max(others, key=lambda c: c[0] * c[1]["weight"])
        term_then_kill(p)
        record("vram", p, f"VRAM {vram_pct:.0f}% full", vram_gb=round(mib / 1024, 1))
        notify("Railguard ended a GPU memory runaway",
               f"{where(p)} held {mib / 1024:.1f} GB of VRAM ({vram_pct:.0f}% full).",
               mood="relieved", say=("rg_vram", p["name"]))
    elif games:
        mib, p = max(games, key=lambda c: c[0])
        record("game-vram", p, f"VRAM {vram_pct:.0f}% full", vram_gb=round(mib / 1024, 1))
        notify("Railguard: the game filled the GPU's memory",
               f"{p['name']} holds {mib / 1024:.1f} GB ({vram_pct:.0f}% full). Left "
               "running -- lower its texture settings if it stutters.",
               say=("rg_game_vram", p["name"]))
        quiet = 300
    else:
        notify("Railguard: GPU memory is full",
               f"VRAM {vram_pct:.0f}% full; no compute process it may end is "
               "listed. railguard.py status shows them.")
    state["quiet"], state["vram"] = max(state["quiet"], time.time() + quiet), 0


def daemon():
    load_settings()
    mtime = 0.0
    state = {"psi": 0, "vram": 0, "quiet": 0.0}
    tick = 0
    card = gpu_card()
    gpu_ok = card is not None
    log("watching" + (f"; VRAM of {card['name']} ({card['source']})" if gpu_ok
                      else "; no graphics card that reports its memory: VRAM not watched"))
    while True:
        time.sleep(TICK)
        tick += 1
        try:
            m = os.stat(SETTINGS_FILE).st_mtime
        except OSError:
            m = 0.0
        if m != mtime:
            mtime = m
            load_settings()
            log("settings: " + json.dumps({k: CFG[k] for k in SETTINGS if k not in LIMITS}))
        if CFG["ram"]:
            check_ram(state, time.time())
        if gpu_ok and CFG["vram"] and tick % GPU_EVERY == 0:
            check_vram(state)


# --- limits --------------------------------------------------------------------

def apply():
    """Write the slices' limits (drop-ins) and set them live; the per-command
    cap goes to the file railguard-run reads."""
    cur = read_settings()
    slices = {"agents.slice": (cur["agents_gb"], cur["agents_threads"]),
              "heavy.slice": (cur["heavy_gb"], cur["heavy_threads"])}
    for name, (gb, threads) in slices.items():
        high = max(1, gb - 2)
        d = os.path.join(UNIT_DIR, name + ".d")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "limits.conf"), "w") as fh:
            fh.write(f"# Written by ~/.config/hypr/scripts/railguard.py from {SETTINGS_FILE}\n"
                     f"# (Settings > Railguard): edits here are overwritten the next time it applies.\n"
                     f"[Slice]\nMemoryHigh={high}G\nMemoryMax={gb}G\nCPUQuota={threads * 100}%\n")
        subprocess.run(["systemctl", "--user", "set-property", "--runtime", name,
                        f"MemoryHigh={high}G", f"MemoryMax={gb}G", f"CPUQuota={threads * 100}%"],
                       capture_output=True)
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(COMMAND_MAX_FILE, "w") as fh:
        fh.write(f"{cur['agent_command_gb']}G\n")
    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)


def set_key(key, value):
    cur = read_settings()
    if key not in SETTINGS or key in LISTS:
        raise SystemExit(f"no setting {key!r} (one of {', '.join(k for k in SETTINGS if k not in LISTS)})")
    if isinstance(SETTINGS[key], bool):
        if value not in ("on", "off", "true", "false"):
            raise SystemExit(f"{key} is on or off")
        cur[key] = value in ("on", "true")
    else:
        lo, hi = RANGES[key]
        try:
            v = float(value)
        except ValueError:
            raise SystemExit(f"{key} is a number, {lo}..{hi}")
        if not lo <= v <= hi:
            raise SystemExit(f"{key} is {lo}..{hi}")
        cur[key] = type(SETTINGS[key])(v)
    write_settings(cur)
    if key in LIMITS:
        apply()


def edit_list(op, key, name):
    if key not in LISTS:
        raise SystemExit(f"the lists are {', '.join(LISTS)}")
    if op == "add" and name in PROTECTED and key == "kill_first":
        raise SystemExit(f"{name} is protected: railguard never ends it")
    cur = read_settings()
    names = set(cur[key])
    (names.add if op == "add" else names.discard)(name)
    cur[key] = sorted(names)
    write_settings(cur)


# --- commands --------------------------------------------------------------------

def slice_info(name):
    out = subprocess.run(
        ["systemctl", "--user", "show", name, "-p", "MemoryCurrent",
         "-p", "MemoryMax", "-p", "TasksCurrent", "-p", "CPUWeight"],
        capture_output=True, text=True).stdout
    v = dict(l.split("=", 1) for l in out.split() if "=" in l)
    num = lambda k: int(v[k]) if v.get(k, "").isdigit() else None  # noqa: E731
    return {"memory": num("MemoryCurrent"), "max": num("MemoryMax"),
            "tasks": num("TasksCurrent"), "cpu_weight": num("CPUWeight")}


def snapshot():
    load_settings()
    m = meminfo()
    st = {"ram_free_pct": round(100.0 * m["MemAvailable"] / m["MemTotal"], 1),
          "swap_used_gb": round((m.get("SwapTotal", 0) - m.get("SwapFree", 0)) / 1024 ** 3, 2),
          "memory_stall_pct": psi_full_avg10(),
          "running": subprocess.run(["systemctl", "--user", "is-active", "railguard.service"],
                                    capture_output=True, text=True).stdout.strip() == "active",
          "settings": CFG, "history": history(20),
          "slices": {s: slice_info(s) for s in ("session.slice", "app.slice", "agents.slice",
                                                "heavy.slice", "background.slice")}}
    card = gpu_card()
    g = gpu_memory(card)
    if g:
        st["gpu_name"] = card["name"]
        st["vram_used_pct"] = round(100.0 * g[0] / g[1], 1)
        st["vram_gb"] = [round(g[0] / 1024, 1), round(g[1] / 1024, 1)]
        st["gpu"] = []
        for pid, mib in sorted(gpu_processes(card).items(), key=lambda x: -x[1]):
            p = proc_info(pid)
            st["gpu"].append({"pid": pid, "mib": mib, "name": p["name"] if p else None,
                              "game": bool(p and p["game"]), "protected": p is None})
    b = biggest()
    if b:
        st["first_to_go"] = {"name": b["name"], "pid": b["pid"], "unit": unit_of(b),
                             "gb": round(b["mem"] / 1024 ** 3, 1)}
    return st


def describe(e):
    when = time.strftime("%b %d %H:%M", time.localtime(e.get("time", 0)))
    what = {"memory": "ended (RAM)", "vram": "ended (VRAM)", "panic": "ended (panic key)",
            "game-vram": "warned, game kept", "stuck": "RAM short, nothing to end",
            "agents": "stopped all agent commands"}.get(e.get("kind"), e.get("kind"))
    name = f"{e['name']} {e.get('gb', 0)} GB" if e.get("name") else ""
    return f"{when}  {what:26} {name}  {e.get('why', '')}".rstrip()


def status(as_json=False):
    st = snapshot()
    if as_json:
        print(json.dumps(st))
        return
    print(f"railguard {'running' if st['running'] else 'NOT running'}   RAM free {st['ram_free_pct']}%   "
          f"swap used {st['swap_used_gb']} GB   memory stall {st['memory_stall_pct']}%")
    if "vram_gb" in st:
        print(f"VRAM {st['vram_gb'][0]} of {st['vram_gb'][1]} GB ({st['vram_used_pct']}%)")
        for g in st["gpu"]:
            tag = " [game]" if g["game"] else " (protected)" if g["protected"] else ""
            print(f"  {g['mib']:6} MiB  {g['name'] or 'pid'} {g['pid']}{tag}")
    for name, s in st["slices"].items():
        cur = gib(s["memory"]) if s["memory"] is not None else "-"
        mx = gib(s["max"]) if s["max"] else "no limit"
        print(f"  {name:16} {cur:>8} of {mx:9}  tasks {s['tasks'] if s['tasks'] is not None else '-':>5}"
              f"  cpu weight {s['cpu_weight']}")
    if "first_to_go" in st:
        f = st["first_to_go"]
        print(f"first to go: {f['name']} (pid {f['pid']}, {f['unit']}), {f['gb']} GB")
    if st["history"]:
        print("last actions:")
        for e in st["history"][:5]:
            print("  " + describe(e))


def panic():
    load_settings()
    m = meminfo()
    if 100.0 * m["MemAvailable"] / m["MemTotal"] < 15:
        p, what = biggest(), "biggest"
        detail = lambda p: gib(p["mem"])  # noqa: E731
    else:
        p, what = busiest(), "busiest"
        detail = lambda p: f"{p['cpu_pct']:.0f}% CPU"  # noqa: E731
    if p and kill(p):
        record("panic", p, f"the {what}: {detail(p)}")
        notify("Railguard: panic", f"ended the {what} process: {where(p)}, {detail(p)}.",
               mood="relieved", say=("rg_panic", p["name"]))
    else:
        notify("Railguard: panic", "found nothing it may end.")


def stop_agents():
    load_settings()
    subprocess.run(["systemctl", "--user", "stop", "agents.slice"])
    record("agents", None, "asked")
    notify("Railguard", "ended every command the agents had running; the sessions stay.",
           mood="relieved", say=("rg_agents",))


def main(argv):
    args = argv[1:]
    cmd = args[0] if args else "status"
    if cmd == "daemon":
        daemon()
    elif cmd == "status":
        status("--json" in args)
    elif cmd == "history":
        n = int(args[args.index("-n") + 1]) if "-n" in args else 50
        h = history(n)
        if "--json" in args:
            print(json.dumps(h))
        else:
            print("\n".join(describe(e) for e in h) or "nothing yet")
    elif cmd == "set" and len(args) == 3:
        set_key(args[1], args[2])
    elif cmd in ("add", "remove") and len(args) == 3:
        edit_list(cmd, args[1], args[2])
    elif cmd == "apply":
        apply()
    elif cmd == "panic":
        panic()
    elif cmd == "stop-agents":
        stop_agents()
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
