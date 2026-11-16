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
    railguard.py add|remove LIST NAME     never_kill / kill_first /
                                          managed_units
    railguard.py apply              write the limits to the slices
    railguard.py panic              end the worst process now: the biggest
                                    when RAM is short, else the busiest
                                    (SUPER+CTRL+ALT+Escape)
    railguard.py stop-agents        end every command the agents started;
                                    the sessions stay

THE DAEMON, once a second (the GPU every 3 s; every 9 s on battery):

    RAM       MemAvailable under ram_free_pct of RAM while swap is
              swap_used_pct full (or there is none), or memory "full"
              pressure (PSI avg10) over stall_pct for stall_s seconds:
              SIGKILL the biggest killable process. Its size is the memory
              ending it would give back: RssAnon + RssShmem + VmSwap, with
              VmLck in place of RssAnon when that is bigger (locked pages
              cannot be reclaimed) -- not VmRSS, which counts a model's
              mmapped weights, file pages the kernel can drop by itself.
    VRAM      vram_pct or more of the GPU's memory for vram_s seconds:
              SIGTERM (SIGKILL 5 s later, from the loop: nothing waits) a
              compute process -- never a game while spare_games is on: when
              the game is the one filling it, it only warns (lower the
              textures), and when something else is (a model, a browser
              tab) that goes, so the game keeps running. Processes the
              driver lists only as graphics are not listed with their
              usage -- then it warns. Which compute process:
                1. one that GREW: within BASE_ZONE_PCT (10) points under
                   vram_pct every check notes each compute process's MiB;
                   when the card crosses, the lowest of those notes from the
                   last BASE_WINDOW_S (30 s) is the baseline (none: the MiB
                   at the crossing). One up GROW_MIB (256) or more since then
                   -- the growth that took the card over counts -- is the
                   runaway, ended at once (growth x weight) -- unless it is
                   a managed engine (2).
                2. a MANAGED engine (its unit -- the cgroup's last part, as
                   history's "unit" -- is on managed_units: cerberus.service,
                   lmstudio.service, cerberus-lmstudio.scope; a dev engine
                   in an agents.slice scope is not managed) is ASKED first: railguard writes the
                   pressure file (PRESSURE below), records "vram-asked" and
                   waits managed_grace_s -- across the loop's ticks, the RAM
                   watch keeps running, the card read every GPU_EVERY even
                   on battery. Under vram_pct again by then:
                   "vram-shed", nothing ended. Still full: it ends a grower
                   if one is left, else the biggest with managed engines
                   weighed x0.5 (they were asked), and the history's why
                   ends in "; asked first" (only then: an ask of this fill
                   went unanswered). After a shed the next fill is asked
                   again; after an ask that ended in an ending it asks again
                   only ASK_AGAIN_S (120 s) later, and an engine that shed
                   SHED_LIMIT (3) times in SHED_WINDOW_S (10 min) is not
                   asked for the next fill -- inside either it acts as after
                   an ask (managed x0.5), with no "; asked first".
                3. nothing grew and nothing is managed: the biggest, as it
                   always did.
              vram_hard_pct or more of what "used" can reach (and full for
              vram_s): no asking, no waiting -- a grower, else the biggest,
              at once. NVIDIA's "used" leaves out the driver's reserve
              (gpu.py vram_reserved, ~455 MiB on a 24 GB card), so used tops
              out near 98 % of the total: vram_pct is of the total (the line
              Cerberus plans under), vram_hard_pct of total - reserved.
    GPU load  not watched: a game at 100 % is the GPU doing its job. When the
              desktop stutters because something else holds the GPU, the
              panic key ends it -- no driver offers a limit for GPU time.
              The card is read in-process (gpu.py: NVML on NVIDIA, sysfs
              and fdinfo on AMD / Intel); with no card that reports its
              memory (an iGPU, none) the VRAM watch is off by itself.

WHO GOES FIRST -- each candidate's size is weighed:

    x4    a name on your kill_first list
    x2    agents.slice, heavy.slice and cerberus-sessions.slice: an
          agent's command (Claude Code's, a Cerberus session's), your build
    x1    everything else (the browser, apps)
    x0.5  session.slice -- programs Hyprland starts live in the
          compositor's own cgroup there -- and games (Steam's SteamAppId,
          Proton's STEAM_COMPAT_APP_ID, Lutris, Heroic)
    never PROTECTED (the compositor, the terminals, their shells, the agent
          sessions: a shell or terminal ended takes its agent with it), your
          never_kill list, anything not yours

After acting it waits 10 s before acting again (30 s after a VRAM end).

LM STUDIO IN AN AGENT'S SCOPE: every minute it looks for llmster (LM
Studio's daemon) or llama-server in agents.slice, heavy.slice or
cerberus-sessions.slice -- any `lms`
call starts the daemon where it was typed, and an agent's command is a scope
there, so every model it loads then has an agent command's cap and weight.
It warns once per daemon (the notification says to run `lms daemon down`,
so that it starts again in lmstudio.service) and ends nothing for it.

ON BATTERY (power_state.py: unplugged, or the battery saver on) only the GPU
half backs off, to every GPU_BATTERY_S. The RAM watch stays at once a
second, on purpose: RAM goes from fine to a frozen desktop in a few seconds
(a 24-thread link step, a model loaded twice), and a freeze costs a reboot
and every agent session's context -- a laptop on battery is no less worth
saving. It is also nearly free: /proc/meminfo and /proc/pressure/memory are
two reads of kernel memory, nothing forked, and stall_s is counted in those
1 s ticks. The GPU query is the part with a cost (NVML, or a walk of the
fdinfo of every process when acting), and VRAM fills more slowly and only
stutters the desktop rather than freezing it; vram_s is counted in seconds,
so the sustained-full rule means the same at either pace (it acts on the
first sample at or past vram_s: 12-15 s at 3 s, 18 s at 9 s). One thing a
slower pace must not do is act on a single reading: at 9 s a sample, any
vram_s from 4 to 9 would be met by the first full one, and a brief spike (a
model loading) would cost a process. So it also takes as many full readings
in a row as the 3 s pace would have needed, up to two -- min(2, vram_s / 3
rounded up): on mains nothing changes (vram_s 3 still acts on one reading,
as it always did; 4 and up needed two anyway), on battery vram_s 4-9 waits
for the second reading.

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
    managed_units     units whose engines are asked to free VRAM before
                      one is ended (["cerberus-lmstudio.scope",
                      "cerberus.service", "lmstudio.service"];
                      [] = never ask); `add|remove managed_units NAME.service`
    managed_grace_s   how long an asked engine has to free it (20; 5..60)
    vram_hard_pct     this full, nothing is asked: it acts at once (99.5;
                      80..100; % of total - reserved, see VRAM above)

Another program may read this file (Cerberus does, to keep its models under
vram_pct); a missing key means the default above. Railguard counts as
present on a machine when railguard.json or railguard-history.jsonl exists.

The limits are written by `apply` as drop-ins (agents.slice.d/limits.conf,
heavy.slice.d/limits.conf; MemoryHigh 2 GB under the cap) and set live with
`systemctl --user set-property --runtime`; the per-command cap is a file
railguard-run reads ($XDG_STATE_HOME/hypr/railguard-command-max).

HISTORY: $XDG_STATE_HOME/hypr/railguard-history.jsonl, one line per action
({"time", "kind", "why", "name", "pid", "unit", "gb", and "vram_gb" for the
VRAM kinds}), the last 500 kept. Settings > Railguard lists it; brief.py's
health section shows the last day's (brief_lines). The kinds:

    memory      ended for RAM          vram        ended for VRAM (why ends
    panic       ended by the panic key             in "; asked first" when a
    stuck       RAM short, nothing to end          managed engine was asked
    game-vram   a game filled the card, kept       for this fill and did not
                                                   free it)
    agents      stop-agents ran        vram-asked  the pressure file was
    vram-shed   VRAM fell under the line           written; name / pid / unit:
                within the grace: nothing          the managed process it
                ended (name / pid / unit: the      would have ended
                one that was asked)

"gb" is the process's size as weighed above: since 2026-11 its anonymous
memory (RssAnon + RssShmem + VmSwap, VmLck when bigger), before that VmRSS +
VmSwap. "vram_gb" is what it held on the card.

PRESSURE: $XDG_STATE_HOME/hypr/railguard-pressure.json, written atomically
(tmp + rename) when it asks managed engines for VRAM instead of ending one:

    {"v": 1, "time": <unix s>, "resource": "vram", "used_mib": N,
     "total_mib": N, "target_mib": N, "act_at": <unix s when it ends one if
     the card is still full>, "managed_units": [...]}

target_mib is PRESSURE_MARGIN_MIB under the vram_pct line. The file is
deleted when the card is under the line again or after it acted (and when
the daemon starts). A reader ignores a file whose "time" is over 60 s old or
whose "v" is not 1. Railguard never reads another program's config or token:
the file is the whole conversation.
"""
import json
import math
import os
import shutil
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import power_state  # noqa: E402  (period(): the GPU check backs off on battery)
STATE_DIR = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "hypr")
SETTINGS_FILE = os.path.join(STATE_DIR, "railguard.json")
HISTORY_FILE = os.path.join(STATE_DIR, "railguard-history.jsonl")
COMMAND_MAX_FILE = os.path.join(STATE_DIR, "railguard-command-max")
UNIT_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
                        "systemd", "user")
PRESSURE_FILE = os.path.join(STATE_DIR, "railguard-pressure.json")
HISTORY_KEEP = 500

SETTINGS = {
    "ram": True, "vram": True, "notify": True,
    "ram_free_pct": 4.0, "swap_used_pct": 80.0, "stall_pct": 50.0, "stall_s": 5,
    "vram_pct": 97.0, "vram_s": 12,
    "spare_games": True, "never_kill": [], "kill_first": [],
    "agent_command_gb": 16, "agents_gb": 20, "heavy_gb": 24,
    "agents_threads": 20, "heavy_threads": 22,
    # cerberus-lmstudio.scope: where Cerberus starts LM Studio's daemon when
    # lmstudio.service is not there (or will not start)
    "managed_units": ["cerberus-lmstudio.scope", "cerberus.service", "lmstudio.service"],
    "managed_grace_s": 20, "vram_hard_pct": 99.5,
}
LISTS = ("never_kill", "kill_first", "managed_units")
LIMITS = ("agent_command_gb", "agents_gb", "heavy_gb", "agents_threads", "heavy_threads")
# the sane range of each number (Settings offers values inside it)
RANGES = {"ram_free_pct": (1, 20), "swap_used_pct": (0, 100), "stall_pct": (10, 95),
          "stall_s": (1, 60), "vram_pct": (80, 100), "vram_s": (3, 120),
          "agent_command_gb": (1, 64), "agents_gb": (2, 64), "heavy_gb": (2, 64),
          "agents_threads": (1, 64), "heavy_threads": (1, 64),
          "managed_grace_s": (5, 60), "vram_hard_pct": (80, 100)}
UNIT_SUFFIXES = (".service", ".scope")   # what a managed_units name may be

TICK = 1.0                    # the RAM watch: never longer (ON BATTERY above says why)
GPU_EVERY = 3                 # seconds between GPU checks, on mains power
GPU_BATTERY_S = 9             # ... and on battery / with the battery saver on
COOLDOWN = 10.0
AGENT_WEIGHT = 2.0            # agents.slice / heavy.slice look this much bigger
SESSION_WEIGHT = 0.5          # session.slice ones this much smaller
GAME_WEIGHT = 0.5             # and games
FIRST_WEIGHT = 4.0            # kill_first names
VRAM_MIN_MIB = 512            # below this a process is not worth ending for VRAM
GROW_MIB = 256                # up this much since before the card crossed the line: a grower
BASE_ZONE_PCT = 10            # within this many points under the line each GPU check notes who holds what
BASE_WINDOW_S = 30            # ... and the lowest of those notes this recent is the growth baseline
MANAGED_WEIGHT = 0.5          # a managed engine that was asked, when one must go anyway
PRESSURE_MARGIN_MIB = 256     # the pressure file's target: this far under the line
ASK_AGAIN_S = 120             # no second ask this soon after an ask that ended in an ending
SHED_LIMIT = 3                # this many sheds within SHED_WINDOW_S: the next fill is not asked
SHED_WINDOW_S = 600
TERM_WAIT = 5.0               # SIGTERM, then SIGKILL this much later
LMS_EVERY = 60                # seconds between looks for LM Studio in an agent's scope
LMS_NAMES = ("llmster", "llama-server")

SESSION_SLICE = "/session.slice/"
BATCH_SLICES = ("/agents.slice/", "/heavy.slice/", "/cerberus-sessions.slice/")
AGENT_SLICES = ("/agents.slice/", "/cerberus-sessions.slice/")   # of those, an agent's commands
GAME_ENV = (b"SteamAppId=", b"STEAM_COMPAT_APP_ID=", b"LUTRIS_GAME_UUID=",
            b"HEROIC_APP_NAME=")
PROTECTED = {
    "Hyprland", "Xwayland", "kitty", "claude", "waybar", "hyprpaper",
    "hypridle", "hyprlock", "mako", "pipewire", "pipewire-pulse",
    "wireplumber", "dbus-broker", "dbus-daemon", "systemd", "uwsm",
    "xdg-desktop-portal", "xdg-desktop-portal-hyprland", "gnome-keyring-d",
    "oo7-daemon",
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
    # an ask is not news by itself: what came of it (vram-shed, or vram) is
    got = [e for e in history(200, since=now - 86400) if e.get("kind") not in ("agents", "vram-asked")]
    if not got:
        return []
    ended = [e for e in got if e["kind"] in ("memory", "vram", "panic")]
    shed = [e for e in got if e["kind"] == "vram-shed"]
    warned = len(got) - len(ended) - len(shed)
    lines = [f"Railguard: {len(ended)} runaway{'s' if len(ended) != 1 else ''} ended in the last day"
             + (f", {len(shed)} time{'s' if len(shed) != 1 else ''} an engine freed GPU memory when asked"
                if shed else "")
             + (f", {warned} warning{'s' if warned != 1 else ''}" if warned else "")
             + " (Settings > Railguard)"]
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


def gpu_usable(card, total):
    """The MiB "used" can reach on CARD of TOTAL: the total less what the
    driver keeps for itself (gpu.py's vram_reserved; NVML's v2 "used" leaves
    that out, so on a 24 GB card used tops out near 98 % of the total). The
    whole total when the card does not say."""
    reserved = (card or {}).get("vram_reserved") or 0
    return total - reserved if 0 < reserved < total else total


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


MEM_FIELDS = ("VmRSS", "RssAnon", "RssShmem", "VmSwap", "VmLck")


def mem_size(status):
    """The bytes ending a process gives back, from its /proc/PID/status
    {field: kB}: RssAnon + RssShmem + VmSwap, with VmLck in place of RssAnon
    when bigger (mlocked pages -- a model loaded with --mlock -- stay put
    whether file-backed or not). VmRSS is left out: it counts mmapped files
    (a model's GGUF weights), pages the kernel drops by itself before it
    runs out. A kernel without RssAnon (before 4.5): VmRSS + VmSwap."""
    if "RssAnon" not in status:
        return (status.get("VmRSS", 0) + status.get("VmSwap", 0)) * 1024
    return (max(status["RssAnon"], status.get("VmLck", 0)) + status.get("RssShmem", 0)
            + status.get("VmSwap", 0)) * 1024


def proc_start(fields):
    """The start time (clock ticks after boot) from stat's fields after the
    name, or None: with the pid it names one process, never a reused pid."""
    try:
        return int(fields[19])
    except (IndexError, ValueError):
        return None


def proc_info(pid):
    """name, cgroup, size in bytes (mem_size), cpu ticks, start time,
    weight, game -- or None when it is gone or not killable."""
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
        status = {}
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                key = line.split(":", 1)[0]
                if key in MEM_FIELDS:
                    status[key] = int(line.split()[1])
        mem = mem_size(status)
    except (OSError, ValueError, IndexError):
        return None
    if name in PROTECTED or name in CFG["never_kill"] or "user@" not in cgroup:
        return None
    game = is_game(pid)
    weight = (FIRST_WEIGHT if name in CFG["kill_first"]
              else AGENT_WEIGHT if any(s in cgroup + "/" for s in BATCH_SLICES)
              else GAME_WEIGHT if game and CFG["spare_games"]
              else SESSION_WEIGHT if SESSION_SLICE in cgroup else 1.0)
    return {"pid": pid, "name": name, "cgroup": cgroup, "mem": mem,
            "ticks": ticks, "start": proc_start(fields), "weight": weight, "game": game}


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


def term_then_kill(p, state=None, wait=TERM_WAIT):
    """SIGTERM, and SIGKILL WAIT seconds later if it is still there. Given
    the daemon's STATE nothing waits here: the SIGKILL is put in
    state["reap"] and reap() sends it from the loop, so the 1 s RAM watch
    never pauses. Without STATE (a one-off command) it waits here."""
    if not kill(p, signal.SIGTERM):
        return False
    if state is not None:
        state.setdefault("reap", []).append({"pid": p["pid"], "start": p.get("start"),
                                             "name": p["name"], "at": time.time() + wait})
        return True
    end = time.time() + wait
    while time.time() < end:
        if not os.path.exists(f"/proc/{p['pid']}"):
            return True
        time.sleep(0.25)
    kill(p)
    return True


def still_there(pid, start):
    """Is the process PID that started at START (proc_start) still running?
    A pid taken over by a new process since is not."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            stat = f.read()
    except OSError:
        return False
    return start is None or proc_start(stat[stat.rindex(")") + 2:].split()) == start


def reap(state, now=None):
    """The SIGKILLs term_then_kill left due: sent once due, to the same
    process only; one that ended by itself is dropped."""
    due = state.get("reap")
    if not due:
        return
    now = time.time() if now is None else now
    keep = []
    for r in due:
        if not still_there(r["pid"], r["start"]):
            continue
        if now < r["at"]:
            keep.append(r)
            continue
        try:
            os.kill(r["pid"], signal.SIGKILL)
            log(f"{r['name']} (pid {r['pid']}) outlived SIGTERM: SIGKILL")
        except OSError:
            pass
    state["reap"] = keep


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


def gpu_every():
    """Seconds until the next GPU check: GPU_EVERY, or GPU_BATTERY_S while
    power_state says to go easy. Asked again after every check, so plugging
    in brings the 3 s pace back at the next one."""
    return power_state.period(GPU_EVERY, GPU_BATTERY_S)


def vram_readings(vram_s):
    """Full readings in a row the VRAM rule needs before it acts: as many as
    the 3 s pace needed, but at most two (see ON BATTERY above)."""
    return min(2, max(1, -(-int(vram_s) // GPU_EVERY)))


ENGINE_NAMES = {"cerberus.service": "Cerberus", "lmstudio.service": "LM Studio",
                "cerberus-lmstudio.scope": "LM Studio"}


def engine_label(unit):
    """What to call a managed unit's engine in a notification."""
    if not unit:
        return "the engine"
    return ENGINE_NAMES.get(unit, unit.rsplit(".", 1)[0])


def is_managed(p):
    """A process of a managed_units unit: its own cgroup's unit, so a model
    server in cerberus.service is, the same server in an agent's
    run-*.scope is not."""
    return unit_of(p) in CFG["managed_units"]


def pressure_target(total):
    """The used MiB an asked engine should get the card down to."""
    return max(0, int(total * CFG["vram_pct"] / 100) - PRESSURE_MARGIN_MIB)


def write_pressure(used, total, act_at, now=None):
    """The pressure file (PRESSURE in the docstring), atomically."""
    now = time.time() if now is None else now
    doc = {"v": 1, "time": int(now), "resource": "vram", "used_mib": int(used),
           "total_mib": int(total), "target_mib": pressure_target(total),
           "act_at": int(math.ceil(act_at)), "managed_units": list(CFG["managed_units"])}
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        tmp = f"{PRESSURE_FILE}.{ME}.tmp"
        with open(tmp, "w") as fh:
            json.dump(doc, fh)
            fh.write("\n")
        os.replace(tmp, PRESSURE_FILE)
    except OSError as exc:
        log(f"pressure file not written: {exc}")
    return doc


def clear_pressure():
    try:
        os.remove(PRESSURE_FILE)
    except FileNotFoundError:
        pass
    except OSError as exc:
        log(f"pressure file not removed: {exc}")


def drop_ask(state):
    """Forget a pending ask without an outcome (the watch went off, the card
    went away): the file goes, nothing is recorded."""
    if state.get("ask"):
        clear_pressure()
    state["ask"] = None


def ask_engine(state, cand, g, vram_pct, now):
    """Ask the managed engines for VRAM instead of ending CAND (the managed
    process it would have ended): the pressure file, a "vram-asked" line,
    and the deadline in state["ask"] that check_vram counts down."""
    mib, _grew, p = cand
    grace = CFG["managed_grace_s"]
    doc = write_pressure(g[0], g[1], now + grace, now)
    label = engine_label(unit_of(p))
    state["ask"] = {"at": now + grace, "since": now, "p": p, "mib": mib, "pct": vram_pct}
    state["asked_at"] = now
    want = max(0, g[0] - doc["target_mib"])
    record("vram-asked", p, f"VRAM {vram_pct:.0f}% full; asked {label} to free {want} MiB "
           f"within {grace} s", vram_gb=round(mib / 1024, 1))
    log(f"VRAM {vram_pct:.0f}% full: asked {label} to free {want} MiB before ending {where(p)}")


def shed(state, ask, vram_pct, now):
    """The card is under the line again while an ask was pending: the engine
    freed it (or something else did) and nothing is ended."""
    p = ask["p"]
    label = engine_label(unit_of(p))
    record("vram-shed", p, f"VRAM {ask['pct']:.0f}% -> {vram_pct:.0f}% within "
           f"{now - ask['since']:.0f} s of asking", vram_gb=round(ask["mib"] / 1024, 1))
    notify(f"Railguard: {label} freed GPU memory",
           f"The card was {ask['pct']:.0f}% full. Railguard asked {label} to free some instead of "
           f"ending {p['name']}, and it did ({vram_pct:.0f}% now). Nothing was ended.",
           mood="relieved")
    clear_pressure()
    state["ask"] = None
    # the engine did what it was asked: the next fill is asked again (asked_at
    # holds back only after an ask that ended in an ending), but an engine
    # that keeps filling the card again is asked at most SHED_LIMIT times
    state.pop("asked_at", None)
    state["sheds"] = [t for t in state.get("sheds", []) if now - t < SHED_WINDOW_S] + [now]


def note_below(state, procs, now):
    """Keep this reading taken under the line (who holds what) for the
    growth baseline; only the last BASE_WINDOW_S of them are kept."""
    seen = [(t, r) for t, r in state.get("seen") or [] if now - t <= BASE_WINDOW_S]
    seen.append((now, dict(procs)))
    state["seen"] = seen


def crossing_base(state, procs, now):
    """{pid: MiB} each process held before the card crossed the line: the
    lowest of the readings taken under it in the last BASE_WINDOW_S, so the
    growth that took the card over counts; a process none of them saw is
    new (base 0). With no recent reading under the line (it jumped from far
    below in one check) the readings now, as before: growth from here on."""
    seen = [r for t, r in state.get("seen") or [] if now - t <= BASE_WINDOW_S]
    state["seen"] = []
    if not seen:
        return dict(procs)
    base = {}
    for r in seen:
        for pid, mib in r.items():
            base[pid] = min(mib, base.get(pid, mib))
    return base


def check_vram(state, every=GPU_EVERY):
    """One GPU sample, EVERY seconds after the last: state["vram"] is how
    long (seconds) the card has been full, so vram_s means the same whatever
    the pace, and state["vram_n"] how many readings in a row it was.
    state["base"] is {pid: MiB} from just before the card crossed the line
    (crossing_base: who grew since), state["seen"] the readings under the
    line it comes from, state["ask"] a pending ask of the managed engines --
    a deadline counted down here, sample by sample, never a sleep.

    vram_pct is measured against the card's total (the line Cerberus plans
    under); vram_hard_pct against what "used" can reach (gpu_usable), so the
    hard rule can fire on a card whose driver keeps a reserve."""
    card = gpu_card()
    g = gpu_memory(card)
    vram_pct = 100.0 * g[0] / g[1] if g else 0.0
    hard = bool(g) and g[0] >= gpu_usable(card, g[1]) * CFG["vram_hard_pct"] / 100
    full = vram_pct >= CFG["vram_pct"] or hard
    state["vram"] = state["vram"] + every if full else 0
    state["vram_n"] = state.get("vram_n", 0) + 1 if full else 0
    now = time.time()
    ask = state.get("ask")
    if not full:
        state["base"] = None
        if g and vram_pct >= CFG["vram_pct"] - BASE_ZONE_PCT:
            note_below(state, gpu_processes(card), now)   # near the line: who holds what
        else:
            state["seen"] = []
        if ask and g:
            shed(state, ask, vram_pct, now)
        elif ask:
            drop_ask(state)                       # no reading: nothing to say about it
        return
    fresh = None
    if state.get("base") is None:                 # it just crossed the line: who held what before
        fresh = gpu_processes(card)
        state["base"] = crossing_base(state, fresh, now)
    if state["vram"] < CFG["vram_s"] or state["vram_n"] < vram_readings(CFG["vram_s"]):
        return
    if not ask and now < state["quiet"]:
        return
    base = state["base"]
    cands = []                                    # (MiB, MiB grown since the line, proc_info)
    for pid, mib in (fresh if fresh is not None else gpu_processes(card)).items():
        p = proc_info(pid)
        if p:
            cands.append((mib, mib - base.get(pid, 0), p))
    spare = CFG["spare_games"]
    others = [c for c in cands if not (spare and c[2]["game"]) and c[0] >= VRAM_MIN_MIB]
    games = [c for c in cands if spare and c[2]["game"]]
    growers = [c for c in others if c[1] >= GROW_MIB]
    loose = [c for c in growers if not is_managed(c[2])]      # a runaway nobody can ask
    managed = [c for c in others if is_managed(c[2])]
    pending = bool(ask)                           # an ask of this fill, not yet answered
    sheds = state["sheds"] = [t for t in state.get("sheds", []) if now - t < SHED_WINDOW_S]
    held = (now - state.get("asked_at", -ASK_AGAIN_S) < ASK_AGAIN_S   # an ask lately ended in an ending
            or len(sheds) >= SHED_LIMIT)          # or it freed the card and filled it again, and again
    asked = pending or held
    if managed and not (hard or loose):
        if ask and now < ask["at"]:
            return                                # the engine still has time
        if not asked:
            ask_engine(state, max(managed, key=lambda c: c[0]), g, vram_pct, now)
            return
    quiet = COOLDOWN * 3
    if others:
        pool = loose or growers or others
        if pool is others:
            size = lambda c: c[0] * c[2]["weight"] * (  # noqa: E731
                MANAGED_WEIGHT if asked and is_managed(c[2]) else 1.0)
        else:
            size = lambda c: c[1] * c[2]["weight"]  # noqa: E731
        mib, grew, p = max(pool, key=size)
        ignored = pending and not loose           # it acted because this fill's ask did not help
        state["sheds"] = []                       # what refilled the card may be gone: count anew
        why = f"VRAM {vram_pct:.0f}% full"
        if grew >= GROW_MIB:
            why += f"; it grew {grew / 1024:.1f} GB"
        if ignored:
            why += "; asked first"
        term_then_kill(p, state)
        record("vram", p, why, vram_gb=round(mib / 1024, 1))
        if ignored and is_managed(p):
            label = engine_label(unit_of(p))
            notify("Railguard ended a GPU memory runaway",
                   f"Railguard asked {label} to free GPU memory and it did not, so {where(p)} was "
                   f"ended: it held {mib / 1024:.1f} GB of VRAM ({vram_pct:.0f}% full).",
                   mood="relieved", say=("rg_vram", p["name"]))
        else:
            notify("Railguard ended a GPU memory runaway",
                   f"{where(p)} held {mib / 1024:.1f} GB of VRAM ({vram_pct:.0f}% full)"
                   + (f" and grew {grew / 1024:.1f} GB since it filled up." if grew >= GROW_MIB else "."),
                   mood="relieved", say=("rg_vram", p["name"]))
    elif games:
        mib, _grew, p = max(games, key=lambda c: c[0])
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
    drop_ask(state)
    state["base"] = None                          # the next time it is full, a new look
    state["quiet"], state["vram"], state["vram_n"] = max(state["quiet"], now + quiet), 0, 0


def lms_in_batch_slices(proc="/proc"):
    """LM Studio's daemon (llmster) and its llama-servers of this user that
    live in agents.slice, heavy.slice or cerberus-sessions.slice (BATCH_SLICES):
    [{pid, name, cgroup}]."""
    out = []
    try:
        entries = os.listdir(proc)
    except OSError:
        return out
    for d in entries:
        if not d.isdigit():
            continue
        where_ = os.path.join(proc, d)
        try:
            with open(os.path.join(where_, "comm")) as f:
                name = f.read().strip()
            if name not in LMS_NAMES or os.stat(where_).st_uid != UID:
                continue
            with open(os.path.join(where_, "cgroup")) as f:
                cgroup = f.read().strip().split("::", 1)[-1]
        except OSError:
            continue
        if any(s in cgroup + "/" for s in BATCH_SLICES):
            out.append({"pid": int(d), "name": name, "cgroup": cgroup})
    return out


def check_lms_scopes(state, proc="/proc"):
    """Warn, once per daemon, about LM Studio running in an agent's command
    or a build (LM STUDIO IN AN AGENT'S SCOPE). Ends nothing. Keyed by the
    llmster pid; a llama-server alone there by its scope."""
    warned = state.setdefault("lms", set())
    groups = {}
    for f in lms_in_batch_slices(proc):
        groups.setdefault(f["cgroup"], []).append(f)
    for cgroup, found in sorted(groups.items()):
        daemons = [f for f in found if f["name"] == "llmster"]
        keys = {f["pid"] for f in daemons} if daemons else {cgroup}
        if keys <= warned:
            continue
        warned |= keys
        f = (daemons or found)[0]
        unit = cgroup.rstrip("/").rsplit("/", 1)[-1]
        sl = "an agent's command" if any(s in cgroup + "/" for s in AGENT_SLICES) else "a heavy build"
        notify("Railguard: LM Studio is running inside " + sl,
               f"{f['name']} (pid {f['pid']}) lives in {unit}, so every model it loads is capped "
               "and ended first like that command. Run `lms daemon down`, then "
               "`systemctl --user start lmstudio.service`, so it runs inside its own limits.")


def daemon():
    load_settings()
    clear_pressure()                              # one left by a daemon that stopped mid-ask
    mtime = 0.0
    state = {"psi": 0, "vram": 0, "vram_n": 0, "quiet": 0.0, "base": None, "ask": None,
             "reap": [], "lms": set()}
    gpu_next, gpu_gap = None, GPU_EVERY      # monotonic time of the next GPU check, and its pace
    lms_next = time.monotonic() + LMS_EVERY  # the first look for LM Studio a minute in
    card = gpu_card()
    gpu_ok = card is not None
    log("watching" + (f"; VRAM of {card['name']} ({card['source']})" if gpu_ok
                      else "; no graphics card that reports its memory: VRAM not watched"))
    while True:
        time.sleep(TICK)
        try:
            m = os.stat(SETTINGS_FILE).st_mtime
        except OSError:
            m = 0.0
        if m != mtime:
            mtime = m
            load_settings()
            log("settings: " + json.dumps({k: CFG[k] for k in SETTINGS if k not in LIMITS}))
        reap(state)
        if CFG["ram"]:
            check_ram(state, time.time())
        if gpu_ok and CFG["vram"]:
            now = time.monotonic()
            if gpu_next is None:
                gpu_next = now + GPU_EVERY      # the first look a few seconds in, as before
            elif now >= gpu_next:
                check_vram(state, gpu_gap)
                # an engine that was asked is watched at the mains pace, even on battery
                gpu_gap = GPU_EVERY if state.get("ask") else gpu_every()
                gpu_next = now + gpu_gap
        elif state.get("ask"):
            drop_ask(state)
        now = time.monotonic()
        if now >= lms_next:
            lms_next = now + LMS_EVERY
            check_lms_scopes(state)


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
    if op == "add" and key == "managed_units" and (
            not name.endswith(UNIT_SUFFIXES) or "/" in name or name.startswith(".")):
        raise SystemExit(f"{name!r} is not a unit: a name like cerberus.service "
                         "(systemctl --user status shows a process's unit)")
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
          "ranges": RANGES,                 # what `set` takes (Settings offers values inside them)
          # the watch's pace now: RAM always 1 s; the GPU slower on battery
          "pace_s": {"ram": TICK, "gpu": gpu_every()},
          "slices": {s: slice_info(s) for s in ("session.slice", "app.slice", "agents.slice",
                                                "heavy.slice", "background.slice")}}
    card = gpu_card()
    g = gpu_memory(card)
    if g:
        st["gpu_name"] = card["name"]
        st["vram_used_pct"] = round(100.0 * g[0] / g[1], 1)
        # the most "used" can reach, % of the total (the driver keeps the rest):
        # Settings offers no vram_pct line above it
        st["vram_usable_pct"] = math.floor(1000.0 * gpu_usable(card, g[1]) / g[1]) / 10
        st["vram_gb"] = [round(g[0] / 1024, 1), round(g[1] / 1024, 1)]
        st["gpu"] = []
        for pid, mib in sorted(gpu_processes(card).items(), key=lambda x: -x[1]):
            p = proc_info(pid)
            st["gpu"].append({"pid": pid, "mib": mib, "name": p["name"] if p else None,
                              "game": bool(p and p["game"]), "protected": p is None,
                              "managed": bool(p and is_managed(p))})
    try:
        with open(PRESSURE_FILE) as fh:
            st["pressure"] = json.load(fh)      # railguard is asking an engine for VRAM now
    except (OSError, ValueError):
        pass
    b = biggest()
    if b:
        st["first_to_go"] = {"name": b["name"], "pid": b["pid"], "unit": unit_of(b),
                             "gb": round(b["mem"] / 1024 ** 3, 1)}
    return st


def describe(e):
    when = time.strftime("%b %d %H:%M", time.localtime(e.get("time", 0)))
    what = {"memory": "ended (RAM)", "vram": "ended (VRAM)", "panic": "ended (panic key)",
            "game-vram": "warned, game kept", "stuck": "RAM short, nothing to end",
            "agents": "stopped all agent commands",
            "vram-asked": f"asked {engine_label(e.get('unit'))} for VRAM",
            "vram-shed": f"{engine_label(e.get('unit'))} freed VRAM"}.get(e.get("kind"), e.get("kind"))
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
            tag = (" [game]" if g["game"] else " (protected)" if g["protected"]
                   else " [managed: asked first]" if g.get("managed") else "")
            print(f"  {g['mib']:6} MiB  {g['name'] or 'pid'} {g['pid']}{tag}")
    if st.get("pressure"):
        pr = st["pressure"]
        print(f"asking {', '.join(pr.get('managed_units', []))} to get VRAM under "
              f"{pr.get('target_mib')} MiB by {time.strftime('%H:%M:%S', time.localtime(pr.get('act_at', 0)))}")
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
