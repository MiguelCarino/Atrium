#!/usr/bin/env python3
"""The graphics cards, whoever made them: load, memory, temperature, power and
who holds the card's memory -- in-process, no nvidia-smi and nothing forked,
so a daemon can ask every few seconds for free (railguard.py, the bar's GPU
pill, its sensors panel, llm-gpu.py and record.sh all come here).

    gpu.py [json]              every card as JSON (the fields below)
    gpu.py vendor              the main card's maker: nvidia | amd | intel |
                               other | none
    gpu.py summary             one line per card, for people
    gpu.py procs [--compute]   {pid: MiB} on the main card, as JSON;
                               --compute keeps the compute processes only:
                               NVIDIA's compute list, AMD's ROCm clients
                               (/dev/kfd); none elsewhere (Intel cannot tell
                               compute from graphics)
    gpu.py table               [{pid, name, mib, sm}] on the main card: every
                               process with its memory and (NVIDIA) its share
                               of the card's compute, biggest first
    gpu.py stream [SECONDS]    "load, temp, used, total, power, fan, which, maker"
                               (CSV, MiB / W / %; "N/A" for what the card
                               does not say) every SECONDS (5) until killed
                               -- the bar's GPU pill reads this (gpu_usage.sh
                               watch). The card the screens are on
                               (display_card), or an offload card while
                               something runs on it: which is "offload" then,
                               else "display"; maker is nvidia | amd | intel |
                               other (the pill's colour). With no card (or one that gives
                               no numbers, like nouveau) it prints "none" once
                               and exits 3
    gpu.py encoder [--json]    what record.sh records with: "gpu nvenc",
                               "gpu vaapi" or "cpu x264" (below)

A CARD (gpus(), sorted: discrete before integrated, then by PCI address;
primary() is the first):

    vendor        nvidia | amd | intel | other
    name          "NVIDIA GeForce RTX 4090", "AMD Radeon RX 7800 XT", ...
    driver        the kernel driver (nvidia, amdgpu, i915, xe, nouveau, ...)
    pci           0000:08:00.0
    card          /sys/class/drm/card1 (None for an NVML-only card)
    discrete      has memory of its own (an iGPU shares the RAM)
    util          load %, temp °C, power W, fan % -- None when not known
    vram_used, vram_total   MiB, None when not known (an iGPU: None)
    source        nvml | sysfs | none: where the numbers came from

WHERE THE NUMBERS COME FROM

    NVIDIA   NVML (libnvidia-ml.so.1, the driver's own library) through
             ctypes, opened once per process and kept: what nvidia-smi
             reads, without starting nvidia-smi (~25-80 ms of CPU each run).
             Per process: compute AND graphics processes with their memory,
             and nvmlDeviceGetProcessUtilization for their SM share. Without
             the driver (nouveau, or NVML missing) the card is still listed,
             with no numbers.
    AMD      amdgpu's sysfs: device/gpu_busy_percent, mem_info_vram_used /
             _total, hwmon temp1_input (edge), power1_average (or _input),
             pwm1. Per process: /proc/<pid>/fdinfo (DRM client stats,
             drm-memory-vram / drm-resident-vram).
    Intel    i915 / xe have no load file: the load is the render engine's
             busy time from /proc/*/fdinfo (i915's drm-engine-render, xe's
             drm-cycles against drm-total-cycles; two samples apart -- the
             stream does that; a one-shot says None), the
             temperature from hwmon where the card has one (Arc). An iGPU
             has no memory of its own: vram None.
    other    listed, no numbers.

Per-process numbers from fdinfo only cover your own processes (the kernel
hides the others'), which is all railguard may end anyway.

THE ENCODER (encoder(), pure part pick_encoder(), tests/test_gpu.py):
gpu-screen-recorder --info lists the codecs it can really open on this
machine (it probes the driver); its answer is kept in
$XDG_RUNTIME_DIR/gpu-encoder.json for the boot (per gsr binary mtime). A
hardware h264 or hevc there -> "gpu" (NVENC on NVIDIA, VAAPI on AMD and
Intel; gsr's own -encoder gpu picks between them); only h264_software ->
"cpu x264". Without gsr, a working NVML says nvenc, a render node on an
AMD/Intel card says vaapi, else cpu.

HYBRID LAPTOPS AND SLEEPING CARDS: a laptop's NVIDIA card is often an
offload card -- no connectors of its own (the screens are all on the
integrated GPU), only used by what is started on it (switcherooctl launch,
the launcher's "Run on <card>"). With runtime power management on
(NVreg_DynamicPowerManagement=0x02, Atrium's system/nvidia-power) the
driver powers it down while nothing holds it, and anything that opens it
-- an NVML query included -- wakes it up. So:
  * a card that is powered down (runtime_status "suspended") is never
    asked: gpus() lists it with source "asleep", load 0, no other numbers,
    and NVML is not even opened while every NVIDIA card sleeps;
  * NVML is let go (nvmlShutdown) as soon as a card that may sleep is
    idle -- no load, no process -- so a daemon that asks every few
    seconds (railguard, the bar) does not keep it awake for ever.
  * display_card() is the card that drives the screens (it has
    connectors); offload_cards() the discrete ones that have none. The bar
    follows the display card and switches to an offload card while
    something runs on it (stream).
primary() stays the first discrete card: the one a model loads onto.

Importable: gpus(), primary(), vendor(), processes(card, compute_only),
process_table(card), Sampler (stream's two-sample Intel load),
encoder(), pick_encoder(info_text, vendor). The roots (/sys, /proc) and the
NVML library are module globals so the tests point them at fakes.
"""
import ctypes
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time

SYS = "/sys"
PROC = "/proc"
PCI_IDS = ("/usr/share/hwdata/pci.ids", "/usr/share/misc/pci.ids")
NVML_LIB = "libnvidia-ml.so.1"
RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
ENCODER_CACHE = os.path.join(RUNTIME, "gpu-encoder.json")
# Each NVML card's memory size by PCI address, kept across boots: a card that
# is powered down cannot be asked, and the launcher's "fits GPU" or railguard
# still need to know how much it has.
VRAM_CACHE = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "gpu-vram.json")
_VRAM = {}
VENDORS = {"0x10de": "nvidia", "0x1002": "amd", "0x1022": "amd", "0x8086": "intel"}
MIB = 2 ** 20
# An NVIDIA card with no process and at most this much memory in use is idle:
# the driver's own context is ~1 MiB.
IDLE_MIB = 16


# -- small readers ---------------------------------------------------------------------------
def _read(path):
    try:
        with open(path) as handle:
            return handle.read().strip()
    except (OSError, UnicodeDecodeError):
        return None


def _int(path):
    text = _read(path)
    try:
        return int(text) if text is not None else None
    except ValueError:
        return None


def _pci(address):
    """NVML's "00000000:08:00.0" and sysfs's "0000:08:00.0" -> the latter, lower case."""
    address = (address or "").strip().lower()
    m = re.match(r"^(?:([0-9a-f]+):)?([0-9a-f]{2}):([0-9a-f]{2})\.([0-7])$", address)
    if not m:
        return address
    return f"{int(m.group(1) or '0', 16):04x}:{m.group(2)}:{m.group(3)}.{m.group(4)}"


_NAMES = {}


def pci_name(vendor_id, device_id):
    """The marketing name from pci.ids ("Navi 32 [Radeon RX 7700 XT / 7800 XT]"),
    None when it is not there. Read once per (vendor, device) per process."""
    key = (vendor_id.lower().removeprefix("0x"), device_id.lower().removeprefix("0x"))
    if key in _NAMES:
        return _NAMES[key]
    name = None
    for path in PCI_IDS:
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                in_vendor = False
                for line in handle:
                    if not line.strip() or line.startswith("#"):
                        continue
                    if not line[0].isspace():
                        in_vendor = line[:4].lower() == key[0]
                        continue
                    if in_vendor and line.startswith("\t") and not line.startswith("\t\t") \
                            and line[1:5].lower() == key[1]:
                        name = line[5:].strip()
                        break
            break
        except OSError:
            continue
    _NAMES[key] = name
    return name


# -- NVIDIA: NVML through ctypes -------------------------------------------------------------
class _Memory(ctypes.Structure):
    _fields_ = [("total", ctypes.c_ulonglong), ("free", ctypes.c_ulonglong), ("used", ctypes.c_ulonglong)]


class _MemoryV2(ctypes.Structure):             # nvmlMemory_v2_t: "used" without the driver's reserve
    _fields_ = [("version", ctypes.c_uint), ("total", ctypes.c_ulonglong), ("reserved", ctypes.c_ulonglong),
                ("free", ctypes.c_ulonglong), ("used", ctypes.c_ulonglong)]


class _Utilization(ctypes.Structure):
    _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]


class _ProcessInfo(ctypes.Structure):          # nvmlProcessInfo_t (the _v2 / _v3 calls)
    _fields_ = [("pid", ctypes.c_uint), ("usedGpuMemory", ctypes.c_ulonglong),
                ("gpuInstanceId", ctypes.c_uint), ("computeInstanceId", ctypes.c_uint)]


class _ProcessInfoV1(ctypes.Structure):        # the unsuffixed calls of old drivers
    _fields_ = [("pid", ctypes.c_uint), ("usedGpuMemory", ctypes.c_ulonglong)]


class _ProcessSample(ctypes.Structure):        # nvmlProcessUtilizationSample_t
    _fields_ = [("pid", ctypes.c_uint), ("timeStamp", ctypes.c_ulonglong), ("smUtil", ctypes.c_uint),
                ("memUtil", ctypes.c_uint), ("encUtil", ctypes.c_uint), ("decUtil", ctypes.c_uint)]


class _PciInfo(ctypes.Structure):              # nvmlPciInfo_t
    _fields_ = [("busIdLegacy", ctypes.c_char * 16), ("domain", ctypes.c_uint), ("bus", ctypes.c_uint),
                ("device", ctypes.c_uint), ("pciDeviceId", ctypes.c_uint), ("pciSubSystemId", ctypes.c_uint),
                ("busId", ctypes.c_char * 32)]


NVML_SUCCESS = 0
NVML_ERROR_INSUFFICIENT_SIZE = 7
NVML_TEMPERATURE_GPU = 0
NOT_AVAILABLE = ctypes.c_ulonglong(-1).value    # NVML_VALUE_NOT_AVAILABLE


class Nvml:
    """NVML, opened on first use and kept for the life of the process (the
    init is the expensive part -- the driver handshake nvidia-smi pays on
    every run). `lib` is a ctypes library or, in the tests, a fake with the
    same functions. Every call degrades: a missing function or an error is
    None / {} for that number, never an exception."""

    def __init__(self, lib=None):
        self.lib = lib
        self.state = None           # None: not tried; True: up; False: no NVML
        self.last_seen = {}         # device index -> the last utilization sample's timestamp

    def ok(self):
        if self.state is None:
            try:
                if self.lib is None:
                    self.lib = ctypes.CDLL(NVML_LIB)
                init = getattr(self.lib, "nvmlInit_v2", None) or self.lib.nvmlInit
                self.state = init() == NVML_SUCCESS
            except (OSError, AttributeError):
                self.state = False
        return self.state

    def close(self):
        """Let go of the driver (nvmlShutdown): an open NVML keeps the card
        out of its powered-down state. The next call opens it again."""
        if self.state:
            self._call(("nvmlShutdown",))
        self.state = None
        self.last_seen = {}

    def _call(self, names, *args):
        for name in names:
            fn = getattr(self.lib, name, None)
            if fn is not None:
                try:
                    return fn(*args)
                except (OSError, TypeError, ValueError):
                    return -1
        return -1

    def count(self):
        if not self.ok():
            return 0
        n = ctypes.c_uint(0)
        return n.value if self._call(("nvmlDeviceGetCount_v2", "nvmlDeviceGetCount"),
                                     ctypes.byref(n)) == NVML_SUCCESS else 0

    def handle(self, index):
        h = ctypes.c_void_p()
        ok = self._call(("nvmlDeviceGetHandleByIndex_v2", "nvmlDeviceGetHandleByIndex"),
                        ctypes.c_uint(index), ctypes.byref(h)) == NVML_SUCCESS
        return h if ok else None

    def _uint(self, names, h, *extra):
        v = ctypes.c_uint(0)
        return v.value if self._call(names, h, *extra, ctypes.byref(v)) == NVML_SUCCESS else None

    def driver(self):
        buf = ctypes.create_string_buffer(96)
        if self.ok() and self._call(("nvmlSystemGetDriverVersion",), buf, ctypes.c_uint(96)) == NVML_SUCCESS:
            return buf.value.decode(errors="replace")
        return None

    def device(self, index):
        """One card's numbers as a gpus() dict (without card / discrete)."""
        h = self.handle(index)
        if h is None:
            return None
        name = ctypes.create_string_buffer(96)
        self._call(("nvmlDeviceGetName",), h, name, ctypes.c_uint(96))
        pci = _PciInfo()
        bus = ""
        if self._call(("nvmlDeviceGetPciInfo_v3", "nvmlDeviceGetPciInfo_v2", "nvmlDeviceGetPciInfo"),
                      h, ctypes.byref(pci)) == NVML_SUCCESS:
            bus = _pci(pci.busId.decode(errors="replace") or pci.busIdLegacy.decode(errors="replace"))
        # _v2 first: its "used" leaves out the memory the driver reserves for
        # itself (~400 MiB on a 24 GB card), the number nvidia-smi shows; the
        # old call counts that reserve as used.
        mem = _MemoryV2(version=ctypes.sizeof(_MemoryV2) | (2 << 24))
        have_mem = self._call(("nvmlDeviceGetMemoryInfo_v2",), h, ctypes.byref(mem)) == NVML_SUCCESS
        if not have_mem:
            mem = _Memory()
            have_mem = self._call(("nvmlDeviceGetMemoryInfo",), h, ctypes.byref(mem)) == NVML_SUCCESS
        util = _Utilization()
        have_util = self._call(("nvmlDeviceGetUtilizationRates",), h, ctypes.byref(util)) == NVML_SUCCESS
        temp = self._uint(("nvmlDeviceGetTemperature",), h, ctypes.c_int(NVML_TEMPERATURE_GPU))
        power = self._uint(("nvmlDeviceGetPowerUsage",), h)
        fan = self._uint(("nvmlDeviceGetFanSpeed",), h)
        return {"vendor": "nvidia", "name": name.value.decode(errors="replace") or "NVIDIA GPU",
                "driver": "nvidia", "pci": bus, "index": index,
                "util": util.gpu if have_util else None,
                "vram_used": mem.used // MIB if have_mem else None,
                "vram_total": mem.total // MIB if have_mem else None,
                "temp": temp, "power": round(power / 1000.0, 1) if power is not None else None,
                "fan": fan, "source": "nvml"}

    def _process_list(self, h, kind):
        """{pid: MiB} from nvmlDeviceGet<kind>RunningProcesses (_v3, _v2, then
        the old one with its smaller struct). A process the driver lists
        without its usage (NOT_AVAILABLE) counts 0."""
        for suffix, struct in (("_v3", _ProcessInfo), ("_v2", _ProcessInfo), ("", _ProcessInfoV1)):
            fn = f"nvmlDevice{kind}RunningProcesses{suffix}"
            if getattr(self.lib, fn, None) is None:
                continue
            size = 64
            for _attempt in range(3):
                count = ctypes.c_uint(size)
                infos = (struct * size)()
                ret = self._call((fn,), h, ctypes.byref(count), infos)
                if ret == NVML_ERROR_INSUFFICIENT_SIZE:
                    size = count.value + 16
                    continue
                if ret != NVML_SUCCESS:
                    return {}
                out = {}
                for info in infos[:min(count.value, size)]:
                    used = info.usedGpuMemory
                    mib = 0 if used in (NOT_AVAILABLE, 0) else used // MIB
                    out[info.pid] = out.get(info.pid, 0) + mib
                return out
            return {}
        return {}

    def processes(self, index, compute_only=False):
        h = self.handle(index) if self.ok() else None
        if h is None:
            return {}
        out = self._process_list(h, "GetCompute")
        if not compute_only:
            for pid, mib in self._process_list(h, "GetGraphics").items():
                out[pid] = max(out.get(pid, 0), mib)    # a C+G process is in both lists
        return out

    def process_util(self, index):
        """{pid: SM %} averaged over the samples since the last call (the
        first call: the driver's whole buffer, a few seconds)."""
        h = self.handle(index) if self.ok() else None
        if h is None or getattr(self.lib, "nvmlDeviceGetProcessUtilization", None) is None:
            return {}
        since = ctypes.c_ulonglong(self.last_seen.get(index, 0))
        count = ctypes.c_uint(0)
        ret = self._call(("nvmlDeviceGetProcessUtilization",), h, None, ctypes.byref(count), since)
        if ret not in (NVML_SUCCESS, NVML_ERROR_INSUFFICIENT_SIZE) or count.value == 0:
            return {}
        size = count.value + 8
        samples = (_ProcessSample * size)()
        count = ctypes.c_uint(size)
        if self._call(("nvmlDeviceGetProcessUtilization",), h, samples, ctypes.byref(count), since) \
                != NVML_SUCCESS:
            return {}
        sums, newest = {}, since.value
        for s in samples[:min(count.value, size)]:
            total, n = sums.get(s.pid, (0, 0))
            sums[s.pid] = (total + s.smUtil, n + 1)
            newest = max(newest, s.timeStamp)
        self.last_seen[index] = newest
        return {pid: round(total / n) for pid, (total, n) in sums.items() if n}


NVML = Nvml()


# -- the cards in sysfs ----------------------------------------------------------------------
def sysfs_cards():
    """[{card, pci, vendor, vendor_id, device_id, driver}] for every DRM card
    (card0, card1, ...; not their connectors), one per PCI device."""
    out, seen = [], set()
    for card in sorted(glob.glob(os.path.join(SYS, "class", "drm", "card[0-9]*")),
                       key=lambda p: int(re.sub(r"\D", "", os.path.basename(p)) or 0)):
        if "-" in os.path.basename(card):
            continue
        dev = os.path.join(card, "device")
        vid = (_read(os.path.join(dev, "vendor")) or "").lower()
        if not vid:
            continue
        pci = _pci(os.path.basename(os.path.realpath(dev)))
        if pci in seen:
            continue
        seen.add(pci)
        try:
            driver = os.path.basename(os.readlink(os.path.join(dev, "driver")))
        except OSError:
            driver = None
        out.append({"card": card, "pci": pci, "vendor": VENDORS.get(vid, "other"), "vendor_id": vid,
                    "device_id": (_read(os.path.join(dev, "device")) or "").lower(), "driver": driver})
    return out


def _hwmon(dev):
    found = sorted(glob.glob(os.path.join(dev, "hwmon", "hwmon*")))
    return found[0] if found else None


def _sysfs_numbers(c):
    """load / memory / temp / power / fan of a non-NVML card from sysfs."""
    dev = os.path.join(c["card"], "device")
    hw = _hwmon(dev)
    used, total = _int(os.path.join(dev, "mem_info_vram_used")), _int(os.path.join(dev, "mem_info_vram_total"))
    temp = _int(os.path.join(hw, "temp1_input")) if hw else None
    power = None
    if hw:
        for f in ("power1_average", "power1_input"):
            power = _int(os.path.join(hw, f))
            if power is not None:
                break
    pwm = _int(os.path.join(hw, "pwm1")) if hw else None
    return {"util": _int(os.path.join(dev, "gpu_busy_percent")),
            "vram_used": used // MIB if used is not None else None,
            "vram_total": total // MIB if total is not None and total > 0 else None,
            "temp": round(temp / 1000) if temp is not None else None,
            "power": round(power / 1e6, 1) if power is not None else None,
            "fan": round(pwm * 100 / 255) if pwm is not None else None}


def _sysfs_name(c):
    dev = os.path.join(c["card"], "device")
    named = _read(os.path.join(dev, "product_name"))
    if named:
        return named
    raw = pci_name(c["vendor_id"], c["device_id"]) if c["device_id"] else None
    maker = {"nvidia": "NVIDIA", "amd": "AMD", "intel": "Intel"}.get(c["vendor"], "GPU")
    if raw:
        # pci.ids: "Navi 32 [Radeon RX 7700 XT / 7800 XT]" -> the bracketed part
        m = re.search(r"\[([^\]]+)\]\s*$", raw)
        return f"{maker} {m.group(1) if m else raw}"
    return f"{maker} GPU ({c['device_id'] or '?'})"


def _discrete(c, numbers):
    """Has memory of its own: NVIDIA always; AMD when it reports 2 GiB of
    VRAM or more (an APU reports its small carve-out of the RAM); Intel only
    an Arc card with local memory (lmem in sysfs)."""
    if c["vendor"] == "nvidia":
        return True
    if c["vendor"] == "amd":
        return (numbers.get("vram_total") or 0) >= 2048
    if c["vendor"] == "intel":
        return bool(glob.glob(os.path.join(c["card"], "device", "lmem*")))
    return False


def asleep(pci):
    """The card is powered down by runtime power management (D3): asking it
    anything would wake it up."""
    return _read(os.path.join(SYS, "bus", "pci", "devices", pci, "power", "runtime_status")) == "suspended"


def may_sleep(pci):
    """The NVIDIA driver powers this card down when it is idle (runtime D3
    on: NVreg_DynamicPowerManagement)."""
    text = _read(os.path.join(PROC, "driver", "nvidia", "gpus", pci, "power")) or ""
    m = re.search(r"Runtime D3 status:\s*(\S+)", text)
    return bool(m) and m.group(1).lower().startswith("enabled")


def _vram_sizes():
    if not _VRAM:
        try:
            with open(VRAM_CACHE) as handle:
                data = json.load(handle)
            _VRAM.update({k: v for k, v in data.items() if isinstance(v, int)})
        except (OSError, ValueError, AttributeError):
            pass
        _VRAM.setdefault("", 0)     # loaded (an empty cache too)
    return _VRAM


def _remember_vram(cards):
    sizes = _vram_sizes()
    new = {g["pci"]: g["vram_total"] for g in cards
           if g.get("source") == "nvml" and g.get("vram_total") and sizes.get(g["pci"]) != g["vram_total"]}
    if not new:
        return
    sizes.update(new)
    try:
        os.makedirs(os.path.dirname(VRAM_CACHE), exist_ok=True)
        tmp = f"{VRAM_CACHE}.{os.getpid()}.tmp"
        with open(tmp, "w") as handle:
            json.dump({k: v for k, v in sizes.items() if k}, handle)
        os.replace(tmp, VRAM_CACHE)
    except OSError:
        pass


def _release_if_idle(nvml, cards):
    """Close NVML when every NVIDIA card it sees may sleep and is idle."""
    nv = [g for g in cards if g.get("source") == "nvml"]
    if nv and all(may_sleep(g["pci"]) and not g["util"] and (g["vram_used"] or 0) <= IDLE_MIB
                  for g in nv):
        nvml.close()


def gpus(nvml=None):
    """Every card, discrete first (see the docstring for the fields)."""
    nvml = nvml or NVML
    cards = sysfs_cards()
    out, nvml_pcis = [], set()
    # Every NVIDIA card powered down: NVML is not opened (it would wake them).
    nv = [c for c in cards if c["vendor"] == "nvidia" and c["driver"] == "nvidia"]
    sleeping = {c["pci"] for c in nv if asleep(c["pci"])}
    if nv and len(sleeping) == len(nv):
        nvml.close()
        for c in nv:
            out.append({"vendor": "nvidia", "name": _sysfs_name(c), "driver": c["driver"], "pci": c["pci"],
                        "card": c["card"], "discrete": True, "index": None, "util": 0, "vram_used": 0,
                        "vram_total": _vram_sizes().get(c["pci"]) or None, "temp": None, "power": None,
                        "fan": None, "source": "asleep"})
            nvml_pcis.add(c["pci"])
    for i in range(0 if sleeping and len(sleeping) == len(nv) else nvml.count()):
        d = nvml.device(i)
        if not d:
            continue
        match = next((c for c in cards if c["pci"] == d["pci"]), None)
        d["card"] = match["card"] if match else None
        d["discrete"] = True
        nvml_pcis.add(d["pci"])
        out.append(d)
    for c in cards:
        if c["pci"] in nvml_pcis:
            continue
        numbers = _sysfs_numbers(c) if c["vendor"] in ("amd", "intel") else dict.fromkeys(
            ("util", "vram_used", "vram_total", "temp", "power", "fan"))
        if c["vendor"] == "intel" and not glob.glob(os.path.join(c["card"], "device", "lmem*")):
            numbers["vram_used"] = numbers["vram_total"] = None    # an iGPU's "memory" is the RAM
        known = any(v is not None for v in numbers.values())
        out.append(dict(numbers, vendor=c["vendor"], name=_sysfs_name(c), driver=c["driver"], pci=c["pci"],
                        card=c["card"], discrete=_discrete(c, numbers), index=None,
                        source="sysfs" if known else "none"))
    out.sort(key=lambda g: (not g["discrete"], g["vendor"] == "other", g["pci"]))
    _remember_vram(out)
    _release_if_idle(nvml, out)
    return out


def has_outputs(card):
    """The card has connectors (eDP-1, HDMI-A-1 ...): it can drive a screen."""
    return bool(card.get("card")) and bool(glob.glob(card["card"] + "-*"))


def display_card(cards=None, nvml=None):
    """The card the screens are on: the first with a connected connector,
    else the first with connectors, else primary()."""
    cards = gpus(nvml) if cards is None else cards
    lit = [g for g in cards if any(_read(os.path.join(c, "status")) == "connected"
                                   for c in glob.glob((g.get("card") or "/nonexistent") + "-*"))]
    return next(iter(lit), None) or next((g for g in cards if has_outputs(g)), None) \
        or (cards[0] if cards else None)


def offload_cards(cards=None, nvml=None):
    """The discrete cards without connectors, on a machine where another
    card has them: render-only cards that run what is started on them."""
    cards = gpus(nvml) if cards is None else cards
    if not any(has_outputs(g) for g in cards):
        return []
    return [g for g in cards if g["discrete"] and g.get("card") and not has_outputs(g)]


def shown_card(cards=None, nvml=None):
    """(card, which) the bar shows: an offload card while something runs on
    it ("offload"), else the display card ("display")."""
    cards = gpus(nvml) if cards is None else cards
    busy = next((g for g in offload_cards(cards) if in_use(g, nvml)), None)
    return (busy, "offload") if busy else (display_card(cards), "display")


def in_use(card, nvml=None):
    """Something runs on this card: awake, with a process or a load."""
    if card.get("source") == "asleep":
        return False
    if card.get("util"):
        return True
    return bool(processes(card, nvml=nvml))


def primary(nvml=None):
    """The card that matters: the first discrete one, else the first one, else None."""
    cards = gpus(nvml)
    return cards[0] if cards else None


def vendor(nvml=None):
    card = primary(nvml)
    return card["vendor"] if card else "none"


# -- per process: NVML, else fdinfo ----------------------------------------------------------
_SIZE = {"": 1, "B": 1, "KiB": 1024, "MiB": MIB, "GiB": 2 ** 30}


def parse_fdinfo(text):
    """One /proc/<pid>/fdinfo/<fd> -> {driver, pdev, client, engines {name:
    ns}, vram bytes} or None when it is not a DRM client. vram is the
    memory in the card's own regions (vram / vram0 / local0): drm-resident-*
    when the driver says it, else drm-total-* / drm-memory-*."""
    fields = {}
    for line in text.splitlines():
        key, _, value = line.partition(":")
        if key.startswith("drm-"):
            fields[key.strip()] = value.strip()
    if "drm-driver" not in fields:
        return None
    engines, vram, cycles = {}, {}, {}
    for key, value in fields.items():
        bits = value.split()
        if not bits or not bits[0].isdigit():
            continue
        n = int(bits[0])
        if key.startswith("drm-engine-") and not key.startswith("drm-engine-capacity-"):
            engines[key[len("drm-engine-"):]] = n
            continue
        # xe has no busy nanoseconds: drm-cycles-<engine> (the client's busy
        # cycles) against drm-total-cycles-<engine> (the GPU's clock)
        if key.startswith("drm-total-cycles-"):
            cycles.setdefault(key[len("drm-total-cycles-"):], [0, 0])[1] = n
            continue
        if key.startswith("drm-cycles-"):
            cycles.setdefault(key[len("drm-cycles-"):], [0, 0])[0] = n
            continue
        m = re.match(r"^drm-(resident|total|memory)-(vram\d*|local\d*)$", key)
        if m:
            unit = bits[1] if len(bits) > 1 else ""
            vram.setdefault(m.group(1), {})[m.group(2)] = n * _SIZE.get(unit, 1)
    picked = vram.get("resident") or vram.get("memory") or vram.get("total") or {}
    return {"driver": fields["drm-driver"], "pdev": _pci(fields.get("drm-pdev", "")),
            "client": fields.get("drm-client-id"), "engines": engines, "vram": sum(picked.values()),
            "cycles": {name: tuple(pair) for name, pair in cycles.items() if pair[1]}}


def drm_clients(proc=None):
    """[(pid, parse_fdinfo dict)] for every DRM client your processes hold,
    each client once (a client id shared by two fds counts once)."""
    proc = proc or PROC
    out, seen = [], set()
    for d in os.listdir(proc):
        if not d.isdigit():
            continue
        fd_dir = os.path.join(proc, d, "fd")
        try:
            fds = os.listdir(fd_dir)
        except OSError:
            continue
        for fd in fds:
            try:
                target = os.readlink(os.path.join(fd_dir, fd))
            except OSError:
                continue
            if not target.startswith("/dev/dri/"):
                continue
            info = parse_fdinfo(_read(os.path.join(proc, d, "fdinfo", fd)) or "")
            if not info:
                continue
            key = (info["pdev"], info["client"] or f"{d}/{fd}")
            if key in seen:
                continue
            seen.add(key)
            out.append((int(d), info))
    return out


def holds(pid, device, proc=None):
    """Does the process have <device> (e.g. /dev/kfd) open?"""
    fd_dir = os.path.join(proc or PROC, str(pid), "fd")
    try:
        fds = os.listdir(fd_dir)
    except OSError:
        return False
    for fd in fds:
        try:
            if os.readlink(os.path.join(fd_dir, fd)) == device:
                return True
        except OSError:
            continue
    return False


def processes(card=None, compute_only=False, nvml=None):
    """{pid: MiB} of the card's memory per process (the main card by default).

    compute_only: NVIDIA's compute list; on AMD the clients that also hold
    /dev/kfd (ROCm / HIP: a model server, not a game or a browser drawing);
    on any other card nothing, since nothing there tells compute from
    graphics -- railguard must never take a browser for a runaway."""
    nvml = nvml or NVML
    card = card or primary(nvml)
    if not card:
        return {}
    if card.get("source") == "asleep":
        return {}
    if card.get("source") == "nvml":
        out = nvml.processes(card["index"], compute_only)
        if not out and not compute_only:
            _release_if_idle(nvml, [card])
        return out
    if compute_only and card.get("vendor") != "amd":
        return {}
    out = {}
    for pid, info in drm_clients():
        if info["pdev"] == card["pci"] and info["vram"]:
            if compute_only and not holds(pid, "/dev/kfd"):
                continue
            out[pid] = out.get(pid, 0) + info["vram"] // MIB
    return out


def _comm(pid):
    return _read(os.path.join(PROC, str(pid), "comm")) or f"pid {pid}"


def process_table(card=None, nvml=None):
    """[{pid, name, mib, sm}] on the card, biggest share of compute first,
    then memory. sm is None where the vendor does not say."""
    nvml = nvml or NVML
    card = card or primary(nvml)
    if not card:
        return []
    mem = processes(card, nvml=nvml)
    sm = nvml.process_util(card["index"]) if card.get("source") == "nvml" else {}
    rows = [{"pid": pid, "name": _comm(pid), "mib": mem.get(pid, 0), "sm": sm.get(pid)}
            for pid in set(mem) | set(sm)]
    rows.sort(key=lambda r: (-(r["sm"] or 0), -r["mib"]))
    return rows


class Sampler:
    """The load of a card that has no load file (Intel): the busiest engine's
    busy nanoseconds (i915) or busy cycles against the GPU clock (xe) summed
    over every client, between two calls."""

    def __init__(self, pci):
        self.pci, self.last = pci, None

    def __call__(self, now=None):
        now = time.monotonic() if now is None else now
        busy, cyc, clock = {}, {}, {}
        for _pid, info in drm_clients():
            if info["pdev"] == self.pci:
                for name, ns in info["engines"].items():
                    busy[name] = busy.get(name, 0) + ns
                for name, (used, total) in info.get("cycles", {}).items():
                    cyc[name] = cyc.get(name, 0) + used
                    clock[name] = max(clock.get(name, 0), total)
        prev, self.last = self.last, (now, busy, cyc, clock)
        if prev is None or now <= prev[0]:
            return None
        span = (now - prev[0]) * 1e9
        loads = [(ns - prev[1].get(name, 0)) / span for name, ns in busy.items() if name in prev[1]]
        loads += [(used - prev[2][name]) / (clock[name] - prev[3][name]) for name, used in cyc.items()
                  if name in prev[2] and clock[name] > prev[3][name]]
        return max(0, min(100, round(100 * max(loads)))) if loads else 0


# -- the encoder for record.sh ---------------------------------------------------------------
def parse_gsr_info(text):
    """gpu-screen-recorder --info -> {"vendor", "codecs": [...]}."""
    section, out = None, {"vendor": None, "codecs": []}
    for line in (text or "").splitlines():
        line = line.strip()
        if line.startswith("section="):
            section = line[len("section="):]
        elif section == "gpu_info" and line.startswith("vendor|"):
            out["vendor"] = line.split("|", 1)[1]
        elif section == "video_codecs" and line and "|" not in line:
            out["codecs"].append(line)
    return out


def pick_encoder(info_text, card_vendor, nvml_ok=False, render_node=False):
    """{"encoder": gpu|cpu, "api": nvenc|vaapi|x264, "hdr": bool, "codecs"}.
    gsr's --info wins (it opened the encoder); without it, a guess from the
    card: NVML up -> nvenc, an AMD/Intel render node -> vaapi, else x264."""
    info = parse_gsr_info(info_text)
    codecs = info["codecs"]
    vendor_ = info["vendor"] or card_vendor
    if codecs:
        hardware = [c for c in codecs if not c.endswith(("_software", "_vulkan"))]
        if any(c in hardware for c in ("h264", "hevc")):
            return {"encoder": "gpu", "api": "nvenc" if vendor_ == "nvidia" else "vaapi",
                    "hdr": "hevc_hdr" in hardware, "codecs": codecs}
        return {"encoder": "cpu", "api": "x264", "hdr": False, "codecs": codecs}
    if card_vendor == "nvidia" and nvml_ok:
        return {"encoder": "gpu", "api": "nvenc", "hdr": True, "codecs": []}
    if card_vendor in ("amd", "intel") and render_node:
        return {"encoder": "gpu", "api": "vaapi", "hdr": card_vendor == "amd", "codecs": []}
    return {"encoder": "cpu", "api": "x264", "hdr": False, "codecs": []}


def encoder(fresh=False):
    gsr = shutil.which("gpu-screen-recorder")
    stamp = os.stat(gsr).st_mtime if gsr else 0
    if not fresh:
        try:
            with open(ENCODER_CACHE) as handle:
                cached = json.load(handle)
            if cached.get("stamp") == stamp:
                return cached["pick"]
        except (OSError, ValueError, KeyError, AttributeError):
            pass
    text = ""
    if gsr:
        try:
            text = subprocess.run([gsr, "--info"], capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            text = ""
    if parse_gsr_info(text)["codecs"]:
        pick = pick_encoder(text, None)         # gsr's answer needs no guess
    else:
        pick = pick_encoder(text, vendor(), NVML.ok(), bool(glob.glob("/dev/dri/renderD*")))
        if gsr:
            return pick     # gsr there but silent (no display yet?): ask again next time
    try:
        tmp = ENCODER_CACHE + ".tmp"
        with open(tmp, "w") as handle:
            json.dump({"stamp": stamp, "pick": pick}, handle)
        os.replace(tmp, ENCODER_CACHE)
    except OSError:
        pass
    return pick


# -- the commands ----------------------------------------------------------------------------
def _csv(card, util, which="display"):
    def v(x):
        return "N/A" if x is None else str(round(x))
    return ", ".join([v(x) for x in (util, card["temp"], card["vram_used"], card["vram_total"],
                                     card["power"], card["fan"])] + [which, card.get("vendor") or "other"])


def stream(seconds=5.0):
    cards = gpus()
    card = display_card(cards)
    # A card whose driver gives no numbers at all (nouveau, a VM's virtual
    # card) is as good as none for the pill: "GPU N/A" forever helps no one.
    # Intel can be all None here and still have a load (the Sampler).
    if not card or (card["source"] == "none" and card["vendor"] != "intel"):
        print("none", flush=True)
        return 3
    sampler = Sampler(card["pci"]) if card["util"] is None and card["vendor"] == "intel" else None
    if sampler:
        sampler()               # the baseline: the first load is the busy time since
        time.sleep(1.0)
    while True:
        cards = gpus()
        card = next((g for g in cards if g["pci"] == card["pci"]), card)
        busy, which = shown_card(cards)
        if which == "offload":
            line = _csv(busy, busy["util"], which)
        else:
            util = card["util"] if card["util"] is not None else (sampler() if sampler else None)
            line = _csv(card, util)
        try:
            print(line, flush=True)
        except BrokenPipeError:
            return 0
        time.sleep(seconds)


def summary_line(g):
    bits = [f"{g['name']} ({g['driver'] or '?'}, {g['pci']})"]
    if g["util"] is not None:
        bits.append(f"load {g['util']}%")
    if g["vram_total"]:
        bits.append(f"VRAM {g['vram_used'] or 0} of {g['vram_total']} MiB")
    if g["temp"] is not None:
        bits.append(f"{g['temp']}°C")
    if g["power"] is not None:
        bits.append(f"{g['power']} W")
    if g["source"] == "none":
        bits.append("no numbers from this driver")
    return "  ".join(bits)


def main(argv):
    cmd = argv[0] if argv else "json"
    if cmd == "json":
        print(json.dumps(gpus(), indent=1))
    elif cmd == "vendor":
        print(vendor())
    elif cmd == "summary":
        cards = gpus()
        for g in cards:
            print(summary_line(g))
        if not cards:
            print("no graphics card found")
    elif cmd == "procs":
        print(json.dumps(processes(compute_only="--compute" in argv)))
    elif cmd == "table":
        print(json.dumps(process_table()))
    elif cmd == "stream":
        try:
            return stream(float(argv[1]) if len(argv) > 1 else 5.0)
        except KeyboardInterrupt:
            return 0
    elif cmd == "encoder":
        pick = encoder(fresh="--fresh" in argv)
        print(json.dumps(pick) if "--json" in argv else f"{pick['encoder']} {pick['api']}")
    else:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
