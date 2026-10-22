#!/usr/bin/env python3
"""What this computer is: hardware, software, the desktop -- for the Settings
window's "About this computer" page (settings_pages/about.py), the search
bar and anyone who asks "what driver am I on?".

    system-info.py                     the whole report as text
    system-info.py text [SECTION...]   the report (or some sections) as text
    system-info.py json [SECTION...]   the same as JSON: [{id, title, rows}]
    system-info.py sections            the section ids and titles
    system-info.py summary             one line: host, model, CPU, GPU, RAM, OS
    system-info.py copy                the whole report to the clipboard (wl-copy)
    system-info.py save [PATH]         the whole report to a text file (default
                                       ~/Documents/system-report-<host>-<date>.txt,
                                       or ~ when there is no Documents folder);
                                       prints where it went
    ... --reveal                       include the identifiers (below)

Sections, in report order:
    computer   host name, model, motherboard, firmware (BIOS version and date,
               UEFI, Secure Boot), uptime, the user and the time zone
    os         Fedora version and its support end, kernel, Hyprland (version,
               commit, Lua or hyprlang config, config errors), the session
               (Wayland, uwsm and its unit, XWayland, the login screen),
               SELinux
    cpu        model, cores / threads, sockets, caches, max and current clock,
               frequency driver / governor / energy preference, temperature
    memory     RAM total / used / available, every swap device, zram
               (algorithm, stored vs compressed)
    gpu        every NVIDIA GPU (nvidia-smi: VRAM, driver, CUDA, PCIe link,
               power, temperature, VBIOS), the kernel module, any other GPU
               lspci sees, the Vulkan devices
    displays   every monitor Hyprland knows (also disabled ones): model,
               resolution, refresh rate, scale, rotation, HDR, colour depth,
               VRR, position, size and pixel density, the best mode it offers
    storage    every disk (model, size, NVMe / SSD / HDD, temperature) with its
               partitions, LVM volumes, file systems, mounts and how full they
               are; each btrfs file system: label, compression, the
               subvolumes mounted and the others found below its mounts
    network    every interface (kind, chip and driver, state, speed, the
               connection, IPv4 / IPv6), the default route, DNS, Bluetooth
    audio      the sound server, every output and input (bus, format, state),
               which ones are the defaults
    versions   the desktop's moving parts: Hyprland and its tools, the panels,
               PipeWire, Mesa / Vulkan / NVIDIA, GTK / libadwaita / Qt,
               Python, systemd, the terminal and browser
    packages   RPM (count, last change), Flatpak (apps, runtimes, remotes), the
               enabled DNF repositories
    look       the desktop theme in use (theme.py) and what it sets: fonts,
               icons, cursor, accent, colour scheme, animations, screen filter

Identifiers: MAC addresses, serial numbers and global IPv6 addresses (the ones
that name this machine on the internet) are left out of the text and JSON
unless --reveal is given, so a report can be pasted into a forum or a bug
report as it is. The Settings page shows them behind its "Show identifiers"
button. Nothing here needs root: what does (memory sticks, every btrfs
subvolume, disk serials on some drives) is said in the row that misses it.

Read-only. Nothing is changed, nothing is sent anywhere: no public IP lookup,
no network call at all. Every command has a timeout, a missing tool leaves
its rows out (or says so), and one failing section never takes the others
with it. The sections are independent so the page can gather each one in its
own thread and fill them in as they arrive (gather(); this module has no GTK
and is cheap to import).

A row is {"name", "value", "lines", "secret", "icon", "error"}: a name, a
short value for the right-hand side, detail lines, {label: value} identifiers,
a Font Awesome glyph, and whether it is a problem report. A section is
{"id", "title", "rows", "facts"}; facts are the few words summary() uses.
"""
import concurrent.futures
import datetime
import glob
import json
import os
import platform
import pwd
import re
import shutil
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
HYPR = os.path.dirname(HERE)
DMI = "/sys/class/dmi/id"

SECTIONS = [("computer", "Computer"), ("os", "Operating system"), ("cpu", "Processor"),
            ("memory", "Memory"), ("gpu", "Graphics"), ("displays", "Displays"),
            ("storage", "Storage"), ("network", "Network"), ("audio", "Sound"),
            ("versions", "Components"), ("packages", "Software"), ("look", "Desktop theme")]
TITLES = dict(SECTIONS)

# Font Awesome 6 Free Solid glyphs, the same font the panels' .ctl-icon uses.
ICON = {"computer": "\uf390", "board": "\uf2db", "firmware": "\uf2c2", "clock": "\uf017",
        "user": "\uf007", "os": "\uf5fd", "kernel": "\uf013", "desktop": "\uf2d2",
        "session": "\uf108", "shield": "\uf3ed", "cpu": "\uf2db", "gauge": "\uf624",
        "temp": "\uf2c9", "memory": "\uf538", "swap": "\uf362", "gpu": "\uf26c",
        "vulkan": "\uf1b2", "display": "\uf390", "disk": "\uf0a0", "btrfs": "\uf5fd",
        "ethernet": "\uf6ff", "wifi": "\uf1eb", "virtual": "\uf0e8", "route": "\uf4d7",
        "dns": "\uf0ac", "bluetooth": "\uf293", "speaker": "\uf028", "mic": "\uf130",
        "server": "\uf233", "parts": "\uf12e", "box": "\uf466", "repo": "\uf1c0",
        "theme": "\uf53f", "font": "\uf031", "icons": "\uf03e", "error": "\uf071"}

# What a board maker leaves in the DMI fields it did not fill in.
GENERIC = {"", "system product name", "system version", "to be filled by o.e.m.",
           "default string", "not applicable", "not specified", "none", "x.x", "o.e.m.",
           "type1productconfigid", "system manufacturer", "0123456789"}
# SMBIOS chassis types (DMI type 3), the ones a desktop or laptop reports.
CHASSIS = {1: "Other", 2: "Unknown", 3: "Desktop", 4: "Low-profile desktop", 5: "Pizza box",
           6: "Mini tower", 7: "Tower", 8: "Portable", 9: "Laptop", 10: "Notebook",
           11: "Handheld", 12: "Docking station", 13: "All-in-one", 14: "Sub-notebook",
           15: "Space-saving", 16: "Lunch box", 17: "Server", 23: "Rack server", 24: "Sealed PC",
           30: "Tablet", 31: "Convertible", 32: "Detachable", 33: "IoT gateway",
           34: "Embedded PC", 35: "Mini PC", 36: "Stick PC"}
# Hyprland's monitor transform numbers.
TRANSFORM = {0: "", 1: "rotated 90°", 2: "rotated 180°", 3: "rotated 270°", 4: "flipped",
             5: "flipped, rotated 90°", 6: "flipped, rotated 180°", 7: "flipped, rotated 270°"}
# The kernel's taint bits (Documentation/admin-guide/tainted-kernels.rst)
# that a desktop actually meets; the rest are named by their number.
TAINT = {0: "proprietary module", 1: "module force-loaded", 4: "machine check", 5: "bad page",
         7: "kernel oops", 9: "kernel warning", 10: "staging driver", 11: "firmware bug worked around",
         12: "out-of-tree module", 13: "unsigned module", 14: "soft lockup", 15: "live patched",
         17: "kernel test module", 18: "Rust test module"}
# Taints a third-party driver (NVIDIA's, VirtualBox's...) leaves by just
# being loaded: no sign that anything went wrong.
TAINT_HARMLESS = {0, 12, 13}
# DRM pixel formats with 10 bits per channel.
DEEP_FORMATS = ("2101010", "16161616")

# (group, [(label, rpm package, command that prints a version)]): the
# versions section. The package is asked first (one rpm call for all of
# them); the command is the fallback for what was not installed from an RPM.
# No fallback for hyprlock / hypridle on purpose: an old build that does not
# know --version would lock the screen / start a second idle daemon.
COMPONENTS = [
    ("Desktop", [("Hyprland", "hyprland", None), ("Aquamarine", "aquamarine", None),
                 ("hyprlock", "hyprlock", None), ("hypridle", "hypridle", None),
                 ("hyprpaper", "hyprpaper", None),
                 ("portal", "xdg-desktop-portal-hyprland", None),
                 ("uwsm", "uwsm", ["uwsm", "--version"])]),
    ("Panels", [("Waybar", "waybar", ["waybar", "--version"]), ("mako", "mako", None),
                ("wofi", "wofi", ["wofi", "--version"]), ("cliphist", "cliphist", None)]),
    ("Sound", [("PipeWire", "pipewire", ["pipewire", "--version"]),
               ("WirePlumber", "wireplumber", ["wireplumber", "--version"])]),
    ("Graphics", [("NVIDIA", None, None), ("Mesa", "mesa-dri-drivers", None),
                  ("Mesa Vulkan", "mesa-vulkan-drivers", None),
                  ("Vulkan loader", "vulkan-loader", None)]),
    ("Toolkits", [("GTK 3", "gtk3", None), ("GTK 4", "gtk4", None), ("libadwaita", "libadwaita", None),
                  ("Qt 6", "qt6-qtbase", None), ("Qt 5", "qt5-qtbase", None),
                  ("PyGObject", "python3-gobject", None)]),
    ("System", [("systemd", "systemd", None), ("glibc", "glibc", None), ("Python", None, None),
                ("bash", "bash", None), ("NetworkManager", "NetworkManager", None),
                ("DNF", "dnf5", None), ("Flatpak", "flatpak", None)]),
    ("Apps", [("kitty", "kitty", ["kitty", "--version"]), ("Firefox", "firefox", None),
              ("Files", "nautilus", None), ("mpv", "mpv", None)]),
]


# -- small helpers ---------------------------------------------------------------------------
def run(*cmd, timeout=10, env=None):
    """A command's stdout, "" when it is missing, fails to start or times out."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env,
                              stdin=subprocess.DEVNULL).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def run_json(*cmd, timeout=10):
    try:
        return json.loads(run(*cmd, timeout=timeout) or "null")
    except ValueError:
        return None


def read(path, default=""):
    try:
        with open(path, errors="replace") as handle:
            return handle.read().strip()
    except OSError:
        return default


def read_int(path, default=None):
    try:
        return int(read(path) or "x")
    except ValueError:
        return default


def make_row(name, value="", lines=(), secret=None, icon="", error=False):
    return {"name": name, "value": value, "lines": [l for l in lines if l], "secret": secret or {},
            "icon": icon, "error": error}


def human_bytes(n, binary=False):
    """4096805658624 -> "4.10 TB" (disks, decimal like their label says);
    binary=True: 33538088960 -> "31.2 GiB" (memory)."""
    if n is None:
        return "?"
    step, units = (1024.0, ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]) if binary else \
        (1000.0, ["B", "kB", "MB", "GB", "TB", "PB"])
    value = float(n)
    for unit in units:
        if abs(value) < step or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.2f} {unit}" if value < 10 else f"{value:.1f} {unit}" if value < 100 \
                else f"{value:.0f} {unit}"
        value /= step
    return "?"


def duration(seconds):
    """66300 -> "18 h 25 min"; 3 days and more drop the minutes."""
    seconds = int(seconds)
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days >= 3:
        return f"{days} days {hours} h"
    if days:
        return f"{days} day{'s' if days != 1 else ''} {hours} h {minutes} min"
    if hours:
        return f"{hours} h {minutes} min"
    return f"{minutes} min"


def dmi_date(text):
    """The BIOS date as DMI writes it (MM/DD/YYYY) -> ISO; anything else as is."""
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", text.strip())
    return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}" if m else text.strip()


def meaningful(*values):
    """The DMI values a board maker actually filled in, joined."""
    out = []
    for v in values:
        v = (v or "").strip()
        if v.lower() not in GENERIC and v not in out:
            out.append(v)
    return " ".join(out)


def pick_model(dmi):
    """The machine's model from the DMI fields: the product when the maker
    named it (a laptop, a prebuilt), else the motherboard (a self-built PC,
    whose product fields say "System Product Name")."""
    product = meaningful(dmi.get("product_name"), dmi.get("product_version"))
    if product:
        vendor = meaningful(dmi.get("sys_vendor"))
        return f"{vendor} {product}".strip() if vendor and not product.startswith(vendor) else product
    board = meaningful(dmi.get("board_name"))
    vendor = meaningful(dmi.get("board_vendor"))
    if board:
        return f"{short_vendor(vendor)} {board}".strip()
    return "unknown model"


def short_vendor(vendor):
    """ "ASUSTeK COMPUTER INC." -> "ASUS": the names the makers go by."""
    known = {"asustek": "ASUS", "micro-star": "MSI", "gigabyte": "Gigabyte", "asrock": "ASRock",
             "lenovo": "Lenovo", "dell": "Dell", "hewlett": "HP", "hp": "HP", "framework": "Framework",
             "intel": "Intel", "supermicro": "Supermicro", "biostar": "Biostar", "acer": "Acer",
             "american megatrends": "AMI", "advanced micro devices": "AMD", "nvidia": "NVIDIA",
             "samsung": "Samsung", "apple": "Apple", "microsoft": "Microsoft", "razer": "Razer"}
    low = (vendor or "").lower()
    for key, name in known.items():
        if low.startswith(key):
            return name
    return (vendor or "").strip()


def parse_kv(text):
    """KEY=value lines (os-release, uevent), quotes removed."""
    out = {}
    for line in text.splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def is_global_ipv6(address):
    """An IPv6 address that reaches the internet (not fe80::, fd00::/8, ::1)."""
    low = address.lower()
    return ":" in low and not (low.startswith(("fe8", "fe9", "fea", "feb", "fc", "fd")) or low == "::1")


# -- computer --------------------------------------------------------------------------------
def dmi_fields():
    names = ("sys_vendor", "product_name", "product_version", "product_family", "board_vendor",
             "board_name", "board_version", "bios_vendor", "bios_version", "bios_date",
             "bios_release", "chassis_type", "chassis_vendor")
    return {n: read(os.path.join(DMI, n)) for n in names}


def secure_boot():
    """"on" / "off" from the SecureBoot EFI variable (4 attribute bytes then
    the value), None without EFI or when it cannot be read."""
    for path in glob.glob("/sys/firmware/efi/efivars/SecureBoot-*"):
        try:
            with open(path, "rb") as handle:
                data = handle.read()
            return "on" if data[-1:] == b"\x01" else "off"
        except OSError:
            return None
    return None


def timezone():
    target = os.path.realpath("/etc/localtime")
    return target.split("zoneinfo/", 1)[1] if "zoneinfo/" in target else time.strftime("%Z")


def gather_computer():
    dmi = dmi_fields()
    host = socket.gethostname()
    chassis = CHASSIS.get(read_int(os.path.join(DMI, "chassis_type"), 2) or 2, "")
    pretty = run("hostnamectl", "--json=short", timeout=3)
    try:
        hn = json.loads(pretty) if pretty else {}
    except ValueError:
        hn = {}
    model = pick_model(dmi)
    rows = [make_row(model, chassis if chassis not in ("Unknown", "Other") else "", [
        f"host name {host}" + (f"  ·  pretty name {hn['PrettyHostname']}" if hn.get("PrettyHostname") else "")],
        icon=ICON["computer"])]
    board = meaningful(dmi.get("board_vendor"), dmi.get("board_name"))
    if board:
        rows.append(make_row("Motherboard", short_vendor(dmi.get("board_vendor")), [
            meaningful(dmi.get("board_name"), dmi.get("board_version")),
            f"made by {dmi['board_vendor']}" if dmi.get("board_vendor") else ""], icon=ICON["board"]))
    sb = secure_boot()
    boot = "UEFI" if os.path.isdir("/sys/firmware/efi") else "legacy BIOS"
    rows.append(make_row("Firmware", dmi.get("bios_version") or "?", [
        f"{dmi.get('bios_vendor') or 'unknown maker'}  ·  dated {dmi_date(dmi.get('bios_date', '')) or '?'}"
        + (f"  ·  release {dmi['bios_release']}" if dmi.get("bios_release") else ""),
        f"booted with {boot}" + (f"  ·  Secure Boot {sb}" if sb else "")], icon=ICON["firmware"]))
    try:
        up = float(read("/proc/uptime").split()[0])
    except (IndexError, ValueError):
        up = None
    if up is not None:
        since = datetime.datetime.now() - datetime.timedelta(seconds=up)
        load = " / ".join(f"{x:.2f}" for x in os.getloadavg())
        rows.append(make_row("Uptime", duration(up), [
            f"on since {since:%a %d %b %H:%M}", f"load {load} (1 / 5 / 15 min, {os.cpu_count()} threads)"],
            icon=ICON["clock"]))
    user = pwd.getpwuid(os.getuid())
    rows.append(make_row("User", user.pw_name, [
        f"shell {os.path.basename(user.pw_shell)}  ·  language {os.environ.get('LANG', '?')}",
        f"time zone {timezone()}"], icon=ICON["user"]))
    return rows, {"host": host, "model": model}


# -- operating system ------------------------------------------------------------------------
def kernel_build_date(version):
    """ "#1 SMP PREEMPT_DYNAMIC Thu Oct 15 15:58:58 UTC 2026" -> "2026-10-15"."""
    m = re.search(r"(\w{3}) (\w{3}) +(\d{1,2}) [\d:]+ (?:\w+ )?(\d{4})\s*$", version)
    if not m:
        return ""
    try:
        return datetime.datetime.strptime(f"{m.group(2)} {m.group(3)} {m.group(4)}", "%b %d %Y").strftime("%Y-%m-%d")
    except ValueError:
        return ""


def taint_line(value):
    """/proc/sys/kernel/tainted -> a line saying why, "" when untainted:
    12288 -> "tainted by a third-party driver (normal with NVIDIA's):
    out-of-tree module, unsigned module" -- harmless; anything else points
    at the kernel log."""
    if not value:
        return ""
    bits = [b for b in range(32) if value >> b & 1]
    names = ", ".join(TAINT.get(b, f"flag {b}") for b in bits)
    if set(bits) <= TAINT_HARMLESS:
        return f"tainted by a third-party driver (normal with NVIDIA's): {names}"
    return f"tainted: {names} (the kernel log says more: journalctl -k -p warning)"


def hypr_config():
    """("Lua", "hyprland.lua + 12 modules in lua/") or ("hyprlang", ...)."""
    lua = os.path.join(HYPR, "hyprland.lua")
    if os.path.exists(lua):
        mods = len(glob.glob(os.path.join(HYPR, "lua", "*.lua")))
        return "Lua", f"hyprland.lua + {mods} modules in lua/"
    if os.path.exists(os.path.join(HYPR, "hyprland.conf")):
        return "hyprlang", "hyprland.conf"
    return "?", "no config found"


def gather_os():
    rel = parse_kv(read("/etc/os-release") or read("/usr/lib/os-release"))
    name = rel.get("PRETTY_NAME") or f"{rel.get('NAME', 'Linux')} {rel.get('VERSION', '')}".strip()
    end = rel.get("SUPPORT_END", "")
    end_line = ""
    if end:
        try:
            left = (datetime.date.fromisoformat(end) - datetime.date.today()).days
            end_line = (f"supported until {end} ({left} days left)" if left >= 0
                        else f"support ended {end}: time to upgrade")
        except ValueError:
            end_line = f"supported until {end}"
    selinux = read("/sys/fs/selinux/enforce")
    sel = {"1": "SELinux enforcing", "0": "SELinux permissive"}.get(selinux, "SELinux off")
    variant = rel.get("VARIANT", "")
    rows = [make_row(name, variant if variant and variant not in name else "", [
        f"{rel.get('ID', '?')} {rel.get('VERSION_ID', '')}  ·  {end_line}" if end_line else "", sel],
        icon=ICON["os"])]
    u = os.uname()
    built = kernel_build_date(u.version)
    flags = [f for f in ("PREEMPT_DYNAMIC", "PREEMPT_RT", "SMP") if f in u.version]
    taint = read_int("/proc/sys/kernel/tainted", 0)
    rows.append(make_row("Kernel", u.release, [
        f"{u.machine}  ·  {' '.join(flags) or 'built'}" + (f"  ·  built {built}" if built else ""),
        taint_line(taint)],
        icon=ICON["kernel"]))
    ver = run_json("hyprctl", "version", "-j", timeout=3) or {}
    kind, where = hypr_config()
    errors = run_json("hyprctl", "configerrors", "-j", timeout=3)
    errs = [e for e in (errors or []) if e]
    if ver:
        commit = (ver.get("commit") or "")[:7]
        rows.append(make_row("Hyprland", ver.get("version") or ver.get("tag", "?"), [
            f"commit {commit}" + (f"  ·  built with Aquamarine {ver['buildAquamarine']}" if ver.get("buildAquamarine") else "")
            + (f"  ·  hyprlang {ver['buildHyprlang']}" if ver.get("buildHyprlang") else ""),
            f"{kind} config: {where}",
            ("no config errors" if errors is not None and not errs else
             f"{len(errs)} config error{'s' if len(errs) != 1 else ''}: {errs[0][:90]}" if errs else "")],
            icon=ICON["desktop"]))
    else:
        rows.append(make_row("Hyprland", "not reachable", [
            "hyprctl did not answer (not running inside the Hyprland session?)", f"{kind} config: {where}"],
            icon=ICON["desktop"]))
    session = os.environ.get("XDG_SESSION_TYPE", "?")
    uwsm = run("uwsm", "--version", timeout=5).strip().split("\n")[0] if shutil.which("uwsm") else ""
    unit = run("systemctl", "--user", "list-units", "--type=service", "--state=active", "--plain",
               "--no-legend", "wayland-wm@*", timeout=4).split()
    dm = os.path.basename(os.path.realpath("/etc/systemd/system/display-manager.service"))
    xw = bool(run("pgrep", "-x", "Xwayland", timeout=3).strip())
    rows.append(make_row("Session", session.capitalize() if session != "?" else "?", [
        f"display {os.environ.get('WAYLAND_DISPLAY', '?')}  ·  desktop {os.environ.get('XDG_CURRENT_DESKTOP', '?')}"
        + ("  ·  XWayland running" if xw else "  ·  no XWayland"),
        (f"started by {uwsm}" + (f" ({unit[0]})" if unit else "")) if uwsm else "not started by uwsm",
        f"login screen: {dm.removesuffix('.service')}" if dm and dm != "display-manager.service" else ""],
        icon=ICON["session"]))
    return rows, {"os": name}


# -- processor -------------------------------------------------------------------------------
def cpu_topology(cpu_root="/sys/devices/system/cpu"):
    """(sockets, cores, threads) from sysfs: the (package, core) pairs."""
    pairs, packages, threads = set(), set(), 0
    for cpu in glob.glob(os.path.join(cpu_root, "cpu[0-9]*")):
        top = os.path.join(cpu, "topology")
        pkg, core = read(os.path.join(top, "physical_package_id")), read(os.path.join(top, "core_id"))
        if pkg == "" and core == "":
            continue
        threads += 1
        packages.add(pkg)
        pairs.add((pkg, core))
    return len(packages), len(pairs), threads


def parse_lscpu(data):
    """lscpu -J -> {field without colon: value}."""
    out = {}
    for item in (data or {}).get("lscpu", []):
        out[item.get("field", "").rstrip(":")] = item.get("data") or ""
        for child in item.get("children", []) or []:
            out[child.get("field", "").rstrip(":")] = child.get("data") or ""
    return out


def cpu_temperature():
    """The CPU's temperature from hwmon (k10temp Tctl/Tdie, coretemp package)."""
    for hw in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
        name = read(os.path.join(hw, "name"))
        if name not in ("k10temp", "coretemp", "zenpower", "cpu_thermal"):
            continue
        best = None
        for inp in sorted(glob.glob(os.path.join(hw, "temp*_input"))):
            lab = read(inp.replace("_input", "_label"))
            val = read_int(inp)
            if val is None:
                continue
            if lab in ("Tdie", "Tctl", "Package id 0") or best is None:
                best = (val / 1000.0, lab or name)
                if lab in ("Tdie", "Package id 0"):
                    break
        if best:
            return best
    return None


def gather_cpu():
    model, micro = "", ""
    for line in read("/proc/cpuinfo").splitlines():
        key, _, value = line.partition(":")
        key = key.strip()
        if key in ("model name", "Model", "Hardware") and not model:
            model = value.strip()
        elif key == "microcode" and not micro:
            micro = value.strip()
    lscpu = parse_lscpu(run_json("lscpu", "-J", timeout=5))
    model = model or lscpu.get("Model name", platform.processor() or "unknown CPU")
    sockets, cores, threads = cpu_topology()
    threads = threads or os.cpu_count() or 0
    base = "/sys/devices/system/cpu/cpu0/cpufreq"
    fmax = read_int(os.path.join(base, "cpuinfo_max_freq"))
    curs = [read_int(p) for p in glob.glob("/sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq")]
    curs = [c for c in curs if c]
    clock = []
    if fmax:
        clock.append(f"up to {fmax / 1e6:.2f} GHz")
    if curs:
        clock.append(f"now {sum(curs) / len(curs) / 1e6:.2f} GHz on average, {max(curs) / 1e6:.2f} GHz busiest")
    caches = "  ·  ".join(f"{k.split()[0]} {lscpu[k].split(' (')[0]}" for k in
                          ("L1d cache", "L2 cache", "L3 cache") if lscpu.get(k))
    virt = lscpu.get("Virtualization", "")
    rows = [make_row(model, f"{cores} cores / {threads} threads" if cores else f"{threads} threads", [
        f"{sockets} socket{'s' if sockets != 1 else ''}  ·  " + "  ·  ".join(clock) if clock else "",
        caches,
        "  ·  ".join(x for x in (f"{virt} virtualisation" if virt else "",
                                 f"microcode {micro}" if micro else "",
                                 lscpu.get("Architecture", platform.machine())) if x)],
        icon=ICON["cpu"])]
    gov = read(os.path.join(base, "scaling_governor"))
    if gov:
        driver = read(os.path.join(base, "scaling_driver"))
        epp = read(os.path.join(base, "energy_performance_preference"))
        boost = read("/sys/devices/system/cpu/cpufreq/boost")
        profile = read("/sys/firmware/acpi/platform_profile")
        rows.append(make_row("Frequency scaling", gov, [
            f"driver {driver}" + (f"  ·  energy preference {epp.replace('_', ' ')}" if epp else ""),
            "  ·  ".join(x for x in (f"boost {'on' if boost == '1' else 'off'}" if boost else "",
                                     f"platform profile {profile}" if profile else "") if x)],
            icon=ICON["gauge"]))
    temp = cpu_temperature()
    if temp:
        rows.append(make_row("Temperature", f"{temp[0]:.0f} °C", [f"sensor {temp[1]}"], icon=ICON["temp"]))
    short = re.sub(r"\s+\d+-Core Processor$|\s+Processor$|\(R\)|\(TM\)|CPU @.*$", "", model).strip()
    return rows, {"cpu": short}


# -- memory ----------------------------------------------------------------------------------
def meminfo(text):
    """/proc/meminfo -> {key: bytes}."""
    out = {}
    for line in text.splitlines():
        key, _, value = line.partition(":")
        parts = value.split()
        if parts and parts[0].isdigit():
            out[key.strip()] = int(parts[0]) * (1024 if len(parts) > 1 and parts[1] == "kB" else 1)
    return out


def parse_swaps(text):
    """/proc/swaps -> [{name, type, size, used, prio}] in bytes."""
    out = []
    for line in text.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 5:
            try:
                out.append({"name": parts[0], "type": parts[1], "size": int(parts[2]) * 1024,
                            "used": int(parts[3]) * 1024, "prio": int(parts[4])})
            except ValueError:
                continue
    return out


def parse_zramctl(text):
    """zramctl --raw --bytes --noheadings --output NAME,ALGORITHM,DISKSIZE,DATA,COMPR,TOTAL."""
    out = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 6:
            try:
                out[parts[0]] = {"algorithm": parts[1], "disksize": int(parts[2]), "data": int(parts[3]),
                                 "compr": int(parts[4]), "total": int(parts[5])}
            except ValueError:
                continue
    return out


def installed_ram(total):
    """What is installed, from MemTotal (the firmware and the kernel keep a
    few hundred MB for themselves): 31.2 GiB -> "32 GB RAM", rounded up to
    the next even number of GB from 4 GB on."""
    gib = total / 2 ** 30
    if gib < 3.5:
        return f"{gib:.1f} GB RAM"
    whole = -(-gib // 1)
    return f"{int(whole + whole % 2)} GB RAM"


def gather_memory():
    mem = meminfo(read("/proc/meminfo"))
    total, avail = mem.get("MemTotal", 0), mem.get("MemAvailable", 0)
    used = total - avail
    rows = [make_row("RAM", human_bytes(total, True), [
        f"in use {human_bytes(used, True)} ({used * 100 // total if total else 0} %)  ·  "
        f"available {human_bytes(avail, True)}",
        f"cache and buffers {human_bytes(mem.get('Cached', 0) + mem.get('Buffers', 0), True)}  ·  "
        f"shared {human_bytes(mem.get('Shmem', 0), True)}",
        "the sticks themselves (speed, slots) need root: sudo dmidecode -t memory"], icon=ICON["memory"])]
    zram = parse_zramctl(run("zramctl", "--raw", "--bytes", "--noheadings", "--output",
                             "NAME,ALGORITHM,DISKSIZE,DATA,COMPR,TOTAL", timeout=4))
    swaps = parse_swaps(read("/proc/swaps"))
    for sw in swaps:
        z = zram.get(sw["name"])
        lines = [f"in use {human_bytes(sw['used'], True)} ({sw['used'] * 100 // sw['size'] if sw['size'] else 0} %)"
                 f"  ·  priority {sw['prio']}"]
        if z:
            ratio = f"{z['data'] / z['compr']:.1f}×" if z["compr"] else "-"
            lines.append(f"zram, {z['algorithm']}: {human_bytes(z['data'], True)} stored in "
                         f"{human_bytes(z['total'], True)} of RAM ({ratio} compression)")
        else:
            lines.append(f"{sw['type']} on disk")
        rows.append(make_row(f"Swap {os.path.basename(sw['name'])}", human_bytes(sw["size"], True), lines,
                             icon=ICON["swap"]))
    if not swaps:
        rows.append(make_row("Swap", "none", ["no swap: a full RAM means closing apps"], icon=ICON["swap"]))
    return rows, {"ram": installed_ram(total)}


# -- graphics --------------------------------------------------------------------------------
NVIDIA_FIELDS = ["name", "driver_version", "memory.total", "memory.used", "pci.bus_id", "temperature.gpu",
                 "power.draw", "power.limit", "pcie.link.gen.max", "pcie.link.width.max",
                 "pcie.link.gen.current", "clocks.max.graphics", "vbios_version", "utilization.gpu"]


def parse_nvidia_csv(text):
    """nvidia-smi --query-gpu=<NVIDIA_FIELDS> --format=csv,noheader,nounits
    -> one dict per GPU; "[N/A]" / "[Not Supported]" become ""."""
    out = []
    for line in text.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < len(NVIDIA_FIELDS):
            continue
        out.append({k: ("" if v.startswith("[") else v) for k, v in zip(NVIDIA_FIELDS, parts)})
    return out


def cuda_version(text):
    """The CUDA version from nvidia-smi's banner (old: "CUDA Version: 12.4",
    new: "CUDA UMD Version: 13.4")."""
    m = re.search(r"CUDA(?: UMD)? Version:\s*([\d.]+)", text)
    return m.group(1) if m else ""


def short_bus(bus):
    """ "00000000:08:00.0" -> "08:00.0" (lspci's form)."""
    bus = bus.strip().lower()
    return bus.split(":", 1)[1] if bus.count(":") == 2 else bus


def parse_lspci_mm(text):
    """lspci -mm lines -> [{bus, class, vendor, device}] (quoted fields)."""
    out = []
    for line in text.splitlines():
        fields = re.findall(r'"([^"]*)"', line)
        bus = line.split(" ", 1)[0]
        if len(fields) >= 3:
            out.append({"bus": bus, "class": fields[0], "vendor": fields[1], "device": fields[2]})
    return out


def parse_vulkan_summary(text):
    """vulkaninfo --summary -> [{deviceName, apiVersion, driverName, driverInfo, deviceType}]."""
    out, cur = [], None
    for line in text.splitlines():
        m = re.match(r"\s*(deviceName|apiVersion|driverName|driverInfo|deviceType)\s*=\s*(.*)", line)
        if not m:
            continue
        if m.group(1) == "apiVersion" and cur is not None and "apiVersion" in cur:
            out.append(cur)
            cur = None
        cur = cur or {}
        cur[m.group(1)] = m.group(2).strip()
    if cur:
        out.append(cur)
    return [d for d in out if d.get("deviceName")]


def gather_gpu():
    rows, facts, nvidia_buses = [], {}, set()
    if shutil.which("nvidia-smi"):
        gpus = parse_nvidia_csv(run("nvidia-smi", f"--query-gpu={','.join(NVIDIA_FIELDS)}",
                                    "--format=csv,noheader,nounits", timeout=10))
        cuda = cuda_version(run("nvidia-smi", timeout=10))
        for g in gpus:
            nvidia_buses.add(short_bus(g["pci.bus_id"]))
            total, used = g["memory.total"], g["memory.used"]
            vram = f"{int(total) / 1024:.0f} GB VRAM" if total.isdigit() else "?"
            power = (f"  ·  drawing {float(g['power.draw']):.0f} W of {float(g['power.limit']):.0f} W"
                     if g["power.draw"] and g["power.limit"] else "")
            link = (f"PCIe {g['pcie.link.gen.max']}.0 x{g['pcie.link.width.max']}"
                    + (f" (gen {g['pcie.link.gen.current']} now, it drops when idle)"
                       if g["pcie.link.gen.current"] and g["pcie.link.gen.current"] != g["pcie.link.gen.max"] else "")
                    if g["pcie.link.gen.max"] else "")
            rows.append(make_row(g["name"], vram, [
                f"driver {g['driver_version']}" + (f"  ·  CUDA {cuda}" if cuda else ""),
                f"VRAM in use {used} of {total} MiB" + (f"  ·  busy {g['utilization.gpu']} %" if g["utilization.gpu"] else ""),
                "  ·  ".join(x for x in (link, f"bus {short_bus(g['pci.bus_id'])}") if x),
                (f"{g['temperature.gpu']} °C" if g["temperature.gpu"] else "") + power
                + (f"  ·  up to {g['clocks.max.graphics']} MHz" if g["clocks.max.graphics"] else ""),
                f"VBIOS {g['vbios_version']}" if g["vbios_version"] else ""], icon=ICON["gpu"]))
            facts.setdefault("gpu", g["name"].replace("NVIDIA GeForce ", "").replace("NVIDIA ", ""))
        if gpus:
            license_ = run("modinfo", "-F", "license", "nvidia", timeout=4).strip()
            modeset = read("/sys/module/nvidia_drm/parameters/modeset")
            fbdev = read("/sys/module/nvidia_drm/parameters/fbdev")
            rows.append(make_row("NVIDIA kernel module", read("/sys/module/nvidia/version") or "?", [
                ("open kernel modules" if "MIT" in license_ or license_ == "Dual MIT/GPL"
                 else "proprietary kernel module" if license_ else ""),
                "  ·  ".join(x for x in (f"modeset {'on' if modeset == 'Y' else 'off'}" if modeset else "",
                                         f"fbdev {'on' if fbdev == 'Y' else 'off'}" if fbdev else "") if x)],
                icon=ICON["kernel"]))
    for dev in parse_lspci_mm(run("lspci", "-mm", timeout=5)):
        if not re.search(r"VGA|3D|Display", dev["class"]) or dev["bus"].lower() in nvidia_buses:
            continue
        driver = os.path.basename(os.path.realpath(f"/sys/bus/pci/devices/0000:{dev['bus']}/driver")) \
            if os.path.exists(f"/sys/bus/pci/devices/0000:{dev['bus']}/driver") else ""
        rows.append(make_row(dev["device"], short_vendor(dev["vendor"]), [
            f"{dev['class']}  ·  bus {dev['bus']}" + (f"  ·  driver {driver}" if driver else "  ·  no driver bound")],
            icon=ICON["gpu"]))
        facts.setdefault("gpu", dev["device"])
    if shutil.which("vulkaninfo"):
        devs = parse_vulkan_summary(run("vulkaninfo", "--summary", timeout=10))
        if devs:
            rows.append(make_row("Vulkan", devs[0].get("apiVersion", ""), [
                f"{d['deviceName']}: Vulkan {d.get('apiVersion', '?')}, {d.get('driverName', '?')} "
                f"{d.get('driverInfo', '')}".rstrip()
                + ("  (software, the fallback)" if "llvmpipe" in d["deviceName"] else "")
                for d in devs], icon=ICON["vulkan"]))
    if not rows:
        rows.append(make_row("No graphics card found", "", ["lspci and nvidia-smi saw none"],
                             icon=ICON["error"], error=True))
    return rows, facts


# -- displays --------------------------------------------------------------------------------
def best_mode(modes):
    """The biggest, then fastest, of Hyprland's availableModes ("3440x1440@180.00Hz")."""
    best = None
    for m in modes or []:
        mm = re.match(r"(\d+)x(\d+)@([\d.]+)", m)
        if mm:
            key = (int(mm.group(1)) * int(mm.group(2)), float(mm.group(3)))
            if best is None or key > best[0]:
                best = (key, f"{mm.group(1)}×{mm.group(2)} @ {float(mm.group(3)):g} Hz")
    return best[1] if best else ""


def diagonal_inches(w_mm, h_mm):
    return (w_mm ** 2 + h_mm ** 2) ** 0.5 / 25.4 if w_mm and h_mm else 0.0


def monitor_row(m):
    """One of `hyprctl monitors all -j` -> a row."""
    w, h = m.get("width", 0), m.get("height", 0)
    rate = m.get("refreshRate", 0)
    name = m.get("name", "?")
    # Hyprland's description is "make model serial": without make and model
    # it is the fallback, minus the serial (an identifier, kept for reveal).
    desc = m.get("description", "") or ""
    if m.get("serial") and desc.endswith(m["serial"]):
        desc = desc[:-len(m["serial"])].rstrip()
    model = " ".join(x for x in (m.get("make", ""), m.get("model", "")) if x) or desc
    if m.get("disabled"):
        return make_row(name, "off", [model, "turned off in the display settings"],
                        {"serial number": m["serial"]} if m.get("serial") else None, ICON["display"])
    preset = m.get("colorManagementPreset", "") or ""
    fmt = m.get("currentFormat", "") or ""
    depth = "10-bit" if any(d in fmt for d in DEEP_FORMATS) else "8-bit" if fmt else ""
    hdr = preset.startswith("hdr")
    look = [f"HDR on ({preset})" if hdr else "SDR" + (f" ({preset})" if preset and preset != "srgb" else ""),
            f"{depth} ({fmt})" if depth else "", f"VRR {'on' if m.get('vrr') else 'off'}"]
    if hdr and m.get("sdrMaxLuminance"):
        look.append(f"SDR white {m['sdrMaxLuminance']:g} nits")
    pw, ph = m.get("physicalWidth", 0), m.get("physicalHeight", 0)
    diag = diagonal_inches(pw, ph)
    ppi = ((w ** 2 + h ** 2) ** 0.5 / diag) if diag else 0
    scale = m.get("scale", 1)
    rot = TRANSFORM.get(m.get("transform", 0), "")
    layout = [f"position {m.get('x', 0)},{m.get('y', 0)}", f"scale {scale:g}" if scale else "", rot,
              f"mirrors {m['mirrorOf']}" if m.get("mirrorOf") not in (None, "", "none") else ""]
    size = f'{diag:.1f}" ({pw}×{ph} mm, {ppi:.0f} ppi)' if diag else ""
    best = best_mode(m.get("availableModes"))
    current = f"{w}×{h} @ {rate:g} Hz" if rate else f"{w}×{h}"
    return make_row(name, f"{w}×{h} @ {rate:.0f} Hz" if rate else f"{w}×{h}", [
        model + (f"  ·  {size}" if size else ""),
        "  ·  ".join(x for x in layout if x) + ("  ·  focused" if m.get("focused") else ""),
        "  ·  ".join(x for x in look if x),
        f"best mode it offers: {best}" if best and best.replace(" ", "") != current.replace(" ", "") else ""],
        {"serial number": m["serial"]} if m.get("serial") else None, ICON["display"])


def gather_displays():
    mons = run_json("hyprctl", "monitors", "all", "-j", timeout=4)
    if not mons:
        return [make_row("No screens reported", "", ["hyprctl did not answer (not inside Hyprland?)"],
                         icon=ICON["error"], error=True)], {}
    mons.sort(key=lambda m: (m.get("disabled", False), m.get("x", 0), m.get("y", 0)))
    return [monitor_row(m) for m in mons], {"screens": f"{sum(not m.get('disabled') for m in mons)} screens"}


# -- storage ---------------------------------------------------------------------------------
LSBLK_COLS = "NAME,PATH,TYPE,SIZE,MODEL,VENDOR,FSTYPE,FSVER,LABEL,UUID,MOUNTPOINTS,TRAN,ROTA,SERIAL,RM"


def disk_kind(dev):
    if dev.get("tran") == "nvme" or dev.get("name", "").startswith("nvme"):
        return "NVMe SSD"
    if dev.get("tran") == "usb":
        return "USB drive"
    if dev.get("rm") in (True, "1"):
        return "removable"
    rota = dev.get("rota")
    return "HDD" if rota in (True, "1") else "SSD"


def usage(mount):
    """(used, size) in bytes of the file system at mount, or None."""
    try:
        st = os.statvfs(mount)
    except OSError:
        return None
    size = st.f_blocks * st.f_frsize
    return (size - st.f_bfree * st.f_frsize, size) if size else None


def disk_temperature(name):
    for inp in glob.glob(f"/sys/block/{name}/device/hwmon*/temp1_input") + \
            glob.glob(f"/sys/block/{name}/device/hwmon/hwmon*/temp1_input"):
        val = read_int(inp)
        if val:
            return val / 1000.0
    return None


def fs_line(node, depth):
    """One partition / volume of a disk as a line."""
    mounts = [m for m in (node.get("mountpoints") or []) if m]
    fstype = node.get("fstype") or ""
    label = f" “{node['label']}”" if node.get("label") else ""
    head = f"{'  ' * depth}{node.get('name')}  {human_bytes(node.get('size'))}"
    if fstype == "swap":
        return f"{head}  swap" + ("  (in use)" if mounts else "")
    if fstype == "LVM2_member":
        return f"{head}  LVM physical volume" + ("" if node.get("children") else " (no active volume)")
    if fstype in ("crypto_LUKS",):
        return f"{head}  encrypted (LUKS)" + ("" if node.get("children") else ", locked")
    if not fstype:
        return f"{head}  {'(no file system)' if not node.get('children') else node.get('type', '')}"
    if mounts:
        real = sorted(mounts, key=len)
        use = usage(real[0])
        full = (f"  ·  {human_bytes(use[0])} used of {human_bytes(use[1])} ({use[0] * 100 // use[1]} %)"
                if use else "")
        return f"{head}  {fstype}{label}  on {', '.join(real[:4])}{' …' if len(real) > 4 else ''}{full}"
    return f"{head}  {fstype}{label}  not mounted"


def walk(node, depth=0):
    """The disk's partitions and the volumes inside them, depth first."""
    for child in node.get("children") or []:
        yield child, depth
        yield from walk(child, depth + 1)


def btrfs_mounts():
    """{fs uuid: [(target, subvol, options)]} from findmnt."""
    data = run_json("findmnt", "-J", "-l", "-t", "btrfs", "-o", "TARGET,SOURCE,UUID,OPTIONS", timeout=4) or {}
    out = {}
    for fs in data.get("filesystems", []):
        opts = dict(o.partition("=")[::2] for o in (fs.get("options") or "").split(","))
        out.setdefault(fs.get("uuid") or fs.get("source"), []).append((fs["target"], opts.get("subvol", "?"), opts))
    return out


SKIP_SCAN = {"/proc", "/sys", "/dev", "/run", "/tmp", "/var/tmp"}
# Where snapshots and container images usually live, looked at on top of the
# first `depth` levels (they are deeper than that below /).
SNAPSHOT_PLACES = (".snapshots", "var/lib/machines", "var/lib/portables",
                   "var/lib/docker/btrfs/subvolumes", "var/lib/containers/storage/btrfs/subvolumes")


def mount_points(mountinfo="/proc/self/mountinfo"):
    """Every mount point (the kernel's list, with its \\040-style escapes undone)."""
    out = set()
    for line in read(mountinfo).splitlines():
        parts = line.split()
        if len(parts) > 4:
            out.add(re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), parts[4]))
    return out


def find_subvolumes(root, depth=2, limit=4000, deadline=None, mounts=None):
    """Subvolumes below a btrfs mount without root: a subvolume's top
    directory always has inode 256 (BTRFS_FIRST_FREE_OBJECTID), and a plain
    directory never does. Two traps, both about how btrfs shows a subvolume:
    the inode has to come from lstat() -- readdir's d_ino (os.scandir's
    DirEntry.inode()) is the subvolume's root id, 257, 258... -- and every
    subvolume has a device number of its own, so os.path.ismount() calls it
    a mount point; the real mount points come from the kernel's list instead.

    Looks `depth` levels down plus SNAPSHOT_PLACES (snapper's
    /.snapshots/<n>/snapshot, systemd's /var/lib/machines, container
    images), never into another mount or into a subvolume it found (a
    snapshot of / is a whole copy of it), and stops after `limit`
    directories or at `deadline` (time.monotonic()) -- this is a summary, the
    full list is `sudo btrfs subvolume list <mount>`."""
    found, seen = [], 0
    deadline = deadline or (time.monotonic() + 1.5)
    mounts = mount_points() if mounts is None else mounts
    todo, visited = [(root, 0)], set()

    def is_subvolume(path):
        try:
            return os.lstat(path).st_ino == 256
        except OSError:
            return False

    for place in SNAPSHOT_PLACES:
        full = os.path.join(root, place)
        if os.path.isdir(full) and not os.path.islink(full) and full not in mounts:
            if is_subvolume(full):
                found.append(full)
            todo.append((full, 0))          # its own `depth` levels: <n>/snapshot
    while todo and seen < limit and time.monotonic() < deadline:
        path, level = todo.pop(0)
        if path in visited:
            continue
        visited.add(path)
        try:
            entries = list(os.scandir(path))
        except OSError:
            continue
        for e in entries:
            seen += 1
            try:
                if not e.is_dir(follow_symlinks=False):
                    continue
            except OSError:
                continue
            full = e.path
            if full in SKIP_SCAN or full in mounts or full in visited:
                continue
            if is_subvolume(full):
                if full not in found:
                    found.append(full)
            elif level + 1 < depth:
                todo.append((full, level + 1))
    return found


def gather_storage():
    data = run_json("lsblk", "-J", "-b", "-o", LSBLK_COLS, timeout=6) or {}
    rows, total = [], 0
    for dev in data.get("blockdevices", []):
        if dev.get("type") != "disk" or dev.get("name", "").startswith(("zram", "loop", "ram", "sr")):
            continue
        total += dev.get("size") or 0
        kind = disk_kind(dev)
        temp = disk_temperature(dev["name"])
        lines = [f"{dev['name']}  ·  {kind}" + (f"  ·  {dev['tran'].upper()}" if dev.get("tran") and
                                                 dev["tran"] != "nvme" else "")
                 + (f"  ·  {temp:.0f} °C" if temp else "")]
        children = list(walk(dev))
        whole = bool(dev.get("fstype"))       # a file system / LVM / LUKS on the whole disk
        if whole:
            lines.append(fs_line(dev, 0))
        elif not children:
            lines.append("no partitions")
        for child, depth in children:
            lines.append(fs_line(child, depth + whole))
        vendor = (dev.get("vendor") or "").strip()
        model = " ".join(x for x in ("" if vendor in ("ATA", "NVMe") else vendor, (dev.get("model") or "").strip()) if x)
        rows.append(make_row(model or dev["name"], human_bytes(dev.get("size")), lines,
                             {"serial number": dev["serial"].strip()} if dev.get("serial") else None, ICON["disk"]))
    labels = {}
    for dev in data.get("blockdevices", []):
        for node, _ in [(dev, 0)] + list(walk(dev)):
            if node.get("fstype") == "btrfs" and node.get("uuid"):
                labels[node["uuid"]] = (node.get("label") or "", node.get("name"))
    deadline = time.monotonic() + 3.0
    for uuid, mounts in btrfs_mounts().items():
        label, devname = labels.get(uuid, ("", "?"))
        opts = mounts[0][2]
        comp = opts.get("compress") or opts.get("compress-force") or "off"
        mounted = sorted({(sub, target) for target, sub, _ in mounts})
        known = {t for _, t in mounted}
        others, mounts_now = [], mount_points()
        for target in sorted(known, key=len):
            for sv in find_subvolumes(target, deadline=deadline, mounts=mounts_now):
                if sv not in known and sv not in others:
                    others.append(sv)
        alloc = f"/sys/fs/btrfs/{uuid}/allocation"
        d_total, d_used = read_int(f"{alloc}/data/total_bytes"), read_int(f"{alloc}/data/bytes_used")
        m_total, m_used = read_int(f"{alloc}/metadata/total_bytes"), read_int(f"{alloc}/metadata/bytes_used")
        lines = [f"on {devname}  ·  compression {comp}"
                 + ("  ·  async discard" if opts.get("discard") == "async" else ""),
                 "mounted subvolumes: " + ", ".join(f"{sub} on {target}" for sub, target in mounted)]
        if d_total:
            lines.append(f"data {human_bytes(d_used)} in {human_bytes(d_total)} allocated  ·  "
                         f"metadata {human_bytes(m_used)} in {human_bytes(m_total)}")
        if others:
            shown = ", ".join(others[:8]) + (f" and {len(others) - 8} more" if len(others) > 8 else "")
            lines.append(f"{len(others)} more subvolume{'s' if len(others) != 1 else ''} found: {shown}")
        lines.append(f"every subvolume and snapshot: sudo btrfs subvolume list {sorted(known, key=len)[0]}")
        count = len(mounted) + len(others)
        rows.append(make_row(f"btrfs “{label}”" if label else "btrfs", f"{count} subvolume{'s' if count != 1 else ''}",
                             lines, icon=ICON["btrfs"]))
    if not rows:
        rows.append(make_row("No disks found", "", ["lsblk did not answer"], icon=ICON["error"], error=True))
    return rows, {"storage": f"{human_bytes(total)} storage"} if total else {}


# -- network ---------------------------------------------------------------------------------
def iface_kind(name, info_kind, link_type):
    if link_type == "loopback":
        return "loopback"
    if os.path.isdir(f"/sys/class/net/{name}/wireless") or os.path.isdir(f"/sys/class/net/{name}/phy80211"):
        return "Wi-Fi"
    if info_kind:
        return {"bridge": "bridge", "tun": "VPN tunnel", "wireguard": "WireGuard", "veth": "container link",
                "vlan": "VLAN", "bond": "bond", "macvlan": "macvlan", "dummy": "dummy"}.get(info_kind, info_kind)
    if link_type in ("none",):
        return "tunnel"
    if os.path.exists(f"/sys/class/net/{name}/device"):
        return "Ethernet" if link_type == "ether" else link_type
    return "virtual"


def parse_resolvectl_dns(text):
    """resolvectl dns -> {"Global": [...], "enp7s0": [...]} (empty ones left out)."""
    out = {}
    for line in text.splitlines():
        head, _, servers = line.partition(":")
        m = re.match(r"Link \d+ \((.+)\)", head.strip())
        key = m.group(1) if m else head.strip()
        if servers.split():
            out[key] = servers.split()
    return out


def pci_name(path):
    """The chip behind a sysfs device, from lspci (one call per device)."""
    slot = os.path.basename(os.path.realpath(path))
    if not re.match(r"[0-9a-f]{4}:[0-9a-f]{2}:", slot):
        return ""
    dev = parse_lspci_mm(run("lspci", "-mm", "-s", slot, timeout=3))
    return f"{short_vendor(dev[0]['vendor'])} {dev[0]['device']}" if dev else ""


USB_VENDORS = {"8087": "Intel", "0bda": "Realtek", "0a12": "CSR", "0cf3": "Qualcomm Atheros",
               "13d3": "IMC (MediaTek)", "0e8d": "MediaTek", "0489": "Foxconn", "04ca": "Lite-On",
               "8086": "Intel", "0a5c": "Broadcom", "2357": "TP-Link"}


def gather_network():
    links = run_json("ip", "-d", "-j", "addr", timeout=4) or []
    routes = run_json("ip", "-j", "route", "show", "default", timeout=4) or []
    nm = {}
    for line in run("nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", timeout=4).splitlines():
        parts = line.split(":")
        if len(parts) >= 4:
            nm[parts[0]] = (parts[2], ":".join(parts[3:]))
    rows = []
    for i in links:
        name = i.get("ifname", "?")
        if i.get("link_type") == "loopback":
            continue
        kind = iface_kind(name, (i.get("linkinfo") or {}).get("info_kind", ""), i.get("link_type", ""))
        state = (i.get("operstate") or "?").lower()
        sysd = f"/sys/class/net/{name}"
        speed = read_int(f"{sysd}/speed") if state == "up" else None
        value = (f"{speed / 1000:g} Gb/s" if speed and speed >= 1000 else f"{speed} Mb/s" if speed and speed > 0
                 else state)
        driver = os.path.basename(os.path.realpath(f"{sysd}/device/driver")) if os.path.exists(f"{sysd}/device/driver") else ""
        chip = pci_name(f"{sysd}/device") if os.path.exists(f"{sysd}/device") else ""
        nm_state, conn = nm.get(name, ("", ""))
        lines = ["  ·  ".join(x for x in (kind, chip, f"driver {driver}" if driver else "") if x)]
        status = nm_state or state
        if conn:
            status += f": {conn}"
        duplex = read(f"{sysd}/duplex") if speed else ""
        lines.append(status + (f"  ·  {duplex} duplex" if duplex else "") + (f"  ·  MTU {i['mtu']}" if i.get("mtu") else ""))
        secret = {}
        if i.get("address") and kind not in ("VPN tunnel", "WireGuard", "tunnel"):
            secret["MAC address"] = i["address"]
        v4 = [f"{a['local']}/{a['prefixlen']}" for a in i.get("addr_info", []) if a.get("family") == "inet"]
        v6 = [a for a in i.get("addr_info", []) if a.get("family") == "inet6"]
        if v4:
            lines.append("IPv4 " + ", ".join(v4))
        local6 = [f"{a['local']}/{a['prefixlen']}" for a in v6 if not is_global_ipv6(a["local"])]
        global6 = [f"{a['local']}/{a['prefixlen']}" for a in v6 if is_global_ipv6(a["local"])]
        if local6:
            lines.append("IPv6 " + ", ".join(local6) + " (local)")
        if global6:
            secret["public IPv6"] = ", ".join(global6)
        gw = [r for r in routes if r.get("dev") == name]
        if gw:
            lines.append(f"default route via {gw[0].get('gateway', '?')}")
        icon = ICON["wifi"] if kind == "Wi-Fi" else ICON["ethernet"] if kind == "Ethernet" else ICON["virtual"]
        rows.append(make_row(name, value, lines, secret, icon))
    # Real hardware first, then the virtual ones; those that are up first within each.
    rows.sort(key=lambda r: (r["icon"] == ICON["virtual"], r["value"] in ("down", "dormant", "lowerlayerdown")))
    dns = parse_resolvectl_dns(run("resolvectl", "dns", timeout=4)) if shutil.which("resolvectl") else {}
    if not dns:
        dns = {"resolv.conf": re.findall(r"^nameserver\s+(\S+)", read("/etc/resolv.conf"), re.M)}
    if any(dns.values()):
        rows.append(make_row("DNS", "", [f"{k}: {', '.join(v)}" for k, v in dns.items() if v], icon=ICON["dns"]))
    for hci in sorted(glob.glob("/sys/class/bluetooth/hci*")):
        if ":" in os.path.basename(hci):
            continue
        blocked = ""
        for rf in glob.glob(f"{hci}/rfkill*"):
            blocked = "turned off" if read(f"{rf}/soft") == "1" or read(f"{rf}/hard") == "1" else "on"
        # The USB device is the parent of the interface hci*/device points
        # at; many adapters (Intel's) have no product string, only ids.
        iface = os.path.realpath(f"{hci}/device")
        usb = os.path.dirname(iface)
        vid, pid = read(os.path.join(usb, "idVendor")), read(os.path.join(usb, "idProduct"))
        driver = os.path.basename(os.path.realpath(f"{iface}/driver")) if os.path.exists(f"{iface}/driver") else ""
        chip = read(os.path.join(usb, "product")) if vid else ""
        if vid and not chip:
            chip = f"{USB_VENDORS.get(vid, 'USB')} adapter ({vid}:{pid})"
        chip += f"  ·  driver {driver}" if driver else ""
        secret = {"address": read(f"{hci}/address")} if read(f"{hci}/address") else None
        rows.append(make_row(f"Bluetooth {os.path.basename(hci)}", blocked or "present",
                             [chip or "adapter"], secret, ICON["bluetooth"]))
    if not rows:
        rows.append(make_row("No network interfaces", "", ["ip did not answer"], icon=ICON["error"], error=True))
    return rows, {}


# -- sound -----------------------------------------------------------------------------------
def audio_row(dev, kind, default):
    props = dev.get("properties", {}) or {}
    spec = dev.get("sample_specification", "")
    m = re.match(r"(\S+) (\d+)ch (\d+)Hz", spec)
    channels = {"1": "mono", "2": "stereo"}.get(m.group(2), f"{m.group(2)} channels") if m else ""
    fmt = f"{m.group(1)}, {channels}, {int(m.group(3)) / 1000:g} kHz" if m else spec
    bus = (props.get("device.bus") or "").upper()
    state = (dev.get("state") or "").lower()
    lines = ["  ·  ".join(x for x in (kind, bus if bus else "virtual", fmt,
                                      {"suspended": "idle", "running": "playing" if kind == "output" else "recording",
                                       "idle": "open"}.get(state, state)) if x)]
    port = dev.get("active_port")
    if port:
        for p in dev.get("ports", []) or []:
            if p.get("name") == port and p.get("description"):
                lines.append(f"port: {p['description']}")
    return make_row(dev.get("description") or dev.get("name", "?"), "default" if default else "", lines,
                    icon=ICON["speaker"] if kind == "output" else ICON["mic"])


def gather_audio():
    if not shutil.which("pactl"):
        return [make_row("No sound server tools", "", ["pactl (pulseaudio-utils) is not installed"],
                         icon=ICON["error"], error=True)], {}
    info = run("pactl", "info", timeout=4)
    kv = {k.strip(): v.strip() for k, _, v in (l.partition(":") for l in info.splitlines())}
    sinks = run_json("pactl", "-f", "json", "list", "sinks", timeout=4) or []
    sources = [s for s in (run_json("pactl", "-f", "json", "list", "sources", timeout=4) or [])
               if not s.get("monitor_source") and not s.get("name", "").endswith(".monitor")]
    cards = run_json("pactl", "-f", "json", "list", "cards", timeout=4) or []
    server = kv.get("Server Name", "")
    m = re.search(r"on PipeWire ([\d.]+)", server)
    rows = [make_row(f"PipeWire {m.group(1)}" if m else server or "no sound server", "", [
        f"PulseAudio {kv['Server Version']} compatible" if kv.get("Server Version") and m else "",
        f"{len(cards)} sound card{'s' if len(cards) != 1 else ''}  ·  {len(sinks)} output{'s' if len(sinks) != 1 else ''}"
        f"  ·  {len(sources)} input{'s' if len(sources) != 1 else ''}",
        f"mixing at {kv['Default Sample Specification']}" if kv.get("Default Sample Specification") else ""],
        icon=ICON["server"], error=not server)]
    dsink, dsource = kv.get("Default Sink", ""), kv.get("Default Source", "")
    for s in sorted(sinks, key=lambda s: s.get("name") != dsink):
        rows.append(audio_row(s, "output", s.get("name") == dsink))
    for s in sorted(sources, key=lambda s: s.get("name") != dsource):
        rows.append(audio_row(s, "input", s.get("name") == dsource))
    return rows, {}


# -- component versions ----------------------------------------------------------------------
def parse_rpm_versions(text):
    """rpm -q --qf '%{NAME}\\t%{VERSION}\\n' output -> {name: version} (the
    "is not installed" lines skipped; multilib duplicates collapse)."""
    out = {}
    for line in text.splitlines():
        name, sep_, version = line.partition("\t")
        if sep_ and version:
            out.setdefault(name.strip(), version.strip())
    return out


def version_from_output(text):
    m = re.search(r"(?<![\d.])(\d+\.\d+(?:\.\d+)*)", text)
    return m.group(1) if m else ""


def gather_versions():
    names = sorted({pkg for _, items in COMPONENTS for _, pkg, _ in items if pkg})
    rpm = parse_rpm_versions(run("rpm", "-q", "--qf", "%{NAME}\t%{VERSION}\n", *names, timeout=10)) \
        if shutil.which("rpm") else {}
    hypr = run_json("hyprctl", "version", "-j", timeout=3) or {}
    rows = []
    for group, items in COMPONENTS:
        found = []
        for label, pkg, cmd in items:
            if label == "Hyprland" and hypr.get("version"):
                version = hypr["version"] + ("" if rpm.get("hyprland") in (None, hypr["version"])
                                             else f" (package {rpm['hyprland']})")
            elif label == "Aquamarine" and not rpm.get(pkg) and hypr.get("buildAquamarine"):
                version = hypr["buildAquamarine"]
            elif label == "NVIDIA":
                version = read("/sys/module/nvidia/version")
            elif label == "Python":
                version = platform.python_version()
            else:
                version = rpm.get(pkg, "")
                if not version and cmd and shutil.which(cmd[0]):
                    version = version_from_output(run(*cmd, timeout=5))
            if version:
                found.append(f"{label} {version}")
        if found:
            rows.append(make_row(group, "", ["  ·  ".join(found)], icon=ICON["parts"]))
    return rows, {}


# -- software --------------------------------------------------------------------------------
def parse_repos(texts):
    """The enabled repository ids in .repo files' text ([id] ... enabled=1;
    a section without enabled= counts as enabled, as dnf does)."""
    out = []
    for text in texts:
        cur, enabled = None, True
        for line in text.splitlines() + ["[]"]:
            line = line.strip()
            m = re.match(r"\[(.*)\]$", line)
            if m:
                if cur and enabled:
                    out.append(cur)
                cur, enabled = m.group(1), True
            elif cur and re.match(r"enabled\s*=", line):
                enabled = line.split("=", 1)[1].strip().lower() in ("1", "true", "yes")
    return out


def short_repo(repo_id):
    """ "copr:copr.fedorainfracloud.org:owner:project" -> "copr owner/project"."""
    parts = repo_id.split(":")
    return f"copr {parts[2]}/{parts[3]}" if parts[0] == "copr" and len(parts) >= 4 else repo_id


def gather_packages():
    rows = []
    if shutil.which("rpm"):
        stamps = []
        for line in run("rpm", "-qa", "--qf", "%{INSTALLTIME} %{NAME}\n", timeout=20).splitlines():
            t, _, n = line.partition(" ")
            if t.isdigit():
                stamps.append((int(t), n))
        if stamps:
            stamps.sort()
            last = datetime.datetime.fromtimestamp(stamps[-1][0])
            first = datetime.datetime.fromtimestamp(stamps[0][0])
            rows.append(make_row("RPM packages", f"{len(stamps)}", [
                f"last change {last:%Y-%m-%d %H:%M} ({stamps[-1][1]})",
                f"oldest package installed {first:%Y-%m-%d} (about when this system was installed)"],
                icon=ICON["box"]))
    if shutil.which("flatpak"):
        apps = [l for l in run("flatpak", "list", "--app", "--columns=application", timeout=15).splitlines() if l.strip()]
        rts = [l for l in run("flatpak", "list", "--runtime", "--columns=application", timeout=15).splitlines() if l.strip()]
        remotes = sorted({l.split()[0] for l in run("flatpak", "remotes", "--columns=name", timeout=10).splitlines() if l.strip()})
        rows.append(make_row("Flatpak", f"{len(apps)} apps", [
            f"{len(rts)} runtimes  ·  remotes: {', '.join(remotes) or 'none'}"], icon=ICON["box"]))
    else:
        rows.append(make_row("Flatpak", "not installed", [], icon=ICON["box"]))
    texts = [read(p) for p in sorted(glob.glob("/etc/yum.repos.d/*.repo"))]
    repos = parse_repos(texts)
    if repos:
        rows.append(make_row("Repositories", f"{len(repos)} enabled", [", ".join(short_repo(r) for r in repos)],
                             icon=ICON["repo"]))
    return rows, {}


# -- desktop theme ---------------------------------------------------------------------------
def gsetting(key, schema="org.gnome.desktop.interface"):
    return run("gsettings", "get", schema, key, timeout=3).strip().strip("'")


def gather_look():
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    try:
        import theme  # noqa: E402  (theme.py: the desktop themes; no GTK)
        name = theme.current()
        conf = theme.load(name)
    except Exception as exc:  # a broken theme file must not hide the rest of the report
        return [make_row("Theme unknown", "", [f"theme.py: {type(exc).__name__}: {exc}"],
                         icon=ICON["error"], error=True)], {}
    status = run_json(os.path.join(HERE, "display.py"), "status", timeout=6) or {}
    accent = status.get("accent") or conf.get("accent") or "the theme's own"
    rows = [make_row(conf.get("name") or name, name, [
        f"accent {accent}" + ("  ·  follows the wallpaper"
                              if status.get("theme_auto") and status.get("accent_follow", True) else ""),
        "  ·  ".join(x for x in (f"animations {status.get('anim') or conf.get('anim', '?')}",
                                 f"window glass {conf.get('glass')} %" if conf.get("glass") else "",
                                 f"screen filter {status['filter']}" if status.get("filter") else "no screen filter")
                     if x)], icon=ICON["theme"])]
    # load() lays the user's own faces (the Fonts page) over the theme's and
    # keeps the theme's as theme:<key>: say which is which.
    def face(key):
        own = conf.get(key, "?")
        theirs = conf.get(f"theme:{key}")
        return own + (f" (yours; the theme's is {theirs})" if theirs and theirs != own else "")
    term = conf.get("term.font", "")
    rows.append(make_row("Fonts", "", [
        f"interface {face('font')}  ·  monospace {face('font_mono')}",
        f"terminal {face('term.font')}" + (f" {conf['term.font_size']} px" if conf.get("term.font_size") else "")
        if term else "",
        f"GTK apps {gsetting('font-name') or '?'}" + (f"  ·  monospace {gsetting('monospace-font-name')}"
                                                       if gsetting("monospace-font-name") else "")],
        icon=ICON["font"]))
    rows.append(make_row("Icons and cursor", "", [
        f"icons {gsetting('icon-theme') or conf.get('icon_theme', '?')}  ·  cursor "
        f"{gsetting('cursor-theme') or conf.get('cursor_theme', '?')} {gsetting('cursor-size')}".rstrip(),
        f"GTK theme {gsetting('gtk-theme') or '?'}  ·  colour scheme {gsetting('color-scheme') or '?'}"
        + (f"  ·  Qt {os.environ['QT_QPA_PLATFORMTHEME']}" if os.environ.get("QT_QPA_PLATFORMTHEME") else "")],
        icon=ICON["icons"]))
    return rows, {"theme": conf.get("name") or name}


GATHER = {"computer": gather_computer, "os": gather_os, "cpu": gather_cpu, "memory": gather_memory,
          "gpu": gather_gpu, "displays": gather_displays, "storage": gather_storage,
          "network": gather_network, "audio": gather_audio, "versions": gather_versions,
          "packages": gather_packages, "look": gather_look}


def gather(section):
    """One section, never raising: a failure becomes an error row."""
    try:
        rows, facts = GATHER[section]()
    except Exception as exc:
        rows, facts = [make_row("Could not read this", "", [f"{type(exc).__name__}: {exc}"],
                                icon=ICON["error"], error=True)], {}
    return {"id": section, "title": TITLES[section], "rows": rows, "facts": facts}


def gather_all(sections=None):
    """Several sections at once (threads: most of the time is waiting on
    commands), in report order."""
    ids = [s for s, _ in SECTIONS if not sections or s in sections]
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(ids) or 1) as pool:
        return list(pool.map(gather, ids))


# -- the report ------------------------------------------------------------------------------
def summary(sections, host=True):
    """ "desktop · Example Board X570 · Ryzen 7 5800X · Radeon RX 6700 XT · 16 GB RAM · Fedora Linux 44"
    (host=False: without the host name, for under a title that is the host name)."""
    facts = {}
    for s in sections:
        facts.update(s.get("facts") or {})
    keys = ("host",) * host + ("model", "cpu", "gpu", "ram", "os")
    return "  ·  ".join(facts[k] for k in keys if facts.get(k))


def row_lines(row, reveal=False):
    """A row as text lines: "name: value", the details indented, the
    identifiers shown or hidden."""
    head = row["name"] + (f": {row['value']}" if row.get("value") else "")
    out = [("! " if row.get("error") else "") + head]
    out += [f"    {line}" for line in row.get("lines", [])]
    for label, value in (row.get("secret") or {}).items():
        out.append(f"    {label}: {value if reveal else '(hidden)'}")
    return out


def report_text(sections, reveal=False, when=None):
    when = when or datetime.datetime.now()
    by_id = {s["id"]: s for s in sections}
    host = next((s["facts"].get("host") for s in sections if s.get("facts", {}).get("host")), socket.gethostname())
    out = [f"System report: {host}, {when:%Y-%m-%d %H:%M}", summary(sections)]
    if not reveal:
        out.append("(MAC addresses, serial numbers and public IPv6 addresses left out)")
    for sid, title in SECTIONS:
        s = by_id.get(sid)
        if not s:
            continue
        out += ["", title.upper()]
        for row in s["rows"]:
            out += ["  " + line for line in row_lines(row, reveal)]
    return "\n".join(out) + "\n"


def public_json(sections, reveal=False):
    """The sections with the identifiers blanked unless reveal."""
    if reveal:
        return sections
    out = []
    for s in sections:
        rows = [dict(r, secret={k: "(hidden)" for k in r.get("secret") or {}}) for r in s["rows"]]
        out.append(dict(s, rows=rows))
    return out


def default_report_path(home=None, when=None, host=None):
    """~/Documents/system-report-<host>-<YYYY-MM-DD-HHMM>.txt, or ~ without
    a Documents folder (xdg-user-dir's answer first, then ~/Documents)."""
    home = home or os.path.expanduser("~")
    when = when or datetime.datetime.now()
    host = re.sub(r"[^A-Za-z0-9._-]", "-", host or socket.gethostname()) or "computer"
    docs = ""
    if home == os.path.expanduser("~") and shutil.which("xdg-user-dir"):
        docs = run("xdg-user-dir", "DOCUMENTS", timeout=3).strip()
        if docs.rstrip("/") == home.rstrip("/"):
            docs = ""
    folder = next((d for d in (docs, os.path.join(home, "Documents")) if d and os.path.isdir(d)), home)
    return os.path.join(folder, f"system-report-{host}-{when:%Y-%m-%d-%H%M}.txt")


def save_report(text, path=None):
    """Write the report (atomically: a temp file then rename) -> the path."""
    path = os.path.expanduser(path) if path else default_report_path()
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    tmp = f"{path}.tmp{os.getpid()}"
    with open(tmp, "w") as handle:
        handle.write(text)
    os.replace(tmp, path)
    return path


def copy_text(text):
    """Put text on the clipboard; True when wl-copy took it."""
    try:
        subprocess.run(["wl-copy", "--type", "text/plain"], input=text, text=True, timeout=5, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def main(argv):
    reveal = "--reveal" in argv
    args = [a for a in argv if a != "--reveal"]
    cmd = args[0] if args else "text"
    rest = args[1:]
    bad = [s for s in rest if s not in TITLES] if cmd in ("text", "json") else []
    if bad:
        sys.exit(f"system-info: no section {', '.join(bad)} (have: {', '.join(TITLES)})")
    if cmd == "sections":
        for sid, title in SECTIONS:
            print(f"{sid}\t{title}")
    elif cmd == "text":
        print(report_text(gather_all(rest), reveal), end="")
    elif cmd == "json":
        print(json.dumps(public_json(gather_all(rest), reveal), indent=1, ensure_ascii=False))
    elif cmd == "summary":
        print(summary(gather_all(["computer", "os", "cpu", "memory", "gpu"])))
    elif cmd == "copy":
        text = report_text(gather_all(), reveal)
        if not copy_text(text):
            sys.exit("system-info: wl-copy failed (is this a Wayland session?)")
        print(f"copied {len(text.splitlines())} lines")
    elif cmd == "save":
        print(save_report(report_text(gather_all(), reveal), rest[0] if rest else None))
    else:
        sys.exit(__doc__.split("\n\n")[1])


if __name__ == "__main__":
    main(sys.argv[1:])
