#!/usr/bin/env python3
"""Sensors panel — what the CPU and GPU pills open.

Small live graphs of the last five minutes, one device per panel, in two
columns: the graphs and readings on the left, the processes on the right.

    CPU   load, temperature, RAM          + top processes by CPU
          MEMORY: RAM and swap in use, memory pressure, and the apps using
          the most RAM, each with an End button (this replaced the separate
          memory pill; the CPU pill already shows RAM in use), and Clear on
          the swap row: swapoff + swapon through pkexec, moving what is in
          swap back into RAM -- offered only while RAM can take it (see
          SWAP_HEADROOM), two clicks like End
    GPU   load, temperature, VRAM, power  + every app on the GPU: its share of
          the GPU's compute (SM %) and its VRAM, with End buttons

The app tables are proctable.py (shared with the network panel): End takes two
clicks and sends SIGTERM; the session's own processes have no button.

The history is not collected here. cpu_usage.sh and gpu_usage.sh already
sample every five seconds for the pills, and in watch mode they also keep their
last 60 samples in $XDG_RUNTIME_DIR/waybar-sensors/{cpu,gpu}.hist. Reading
those means the graphs are full the moment the panel opens, rather than
starting empty and filling in while you watch. If a file is missing (the bar
has not been reloaded since this was added), the graph says so.

Graphs are drawn with cairo: a filled area under a line in the section's neon
(CPU magenta, GPU green, matching the pills' labels), with the line drawn twice
-- wide and faint, then thin and bright -- which is the glow.

Not run directly: cpu_panel.py and gpu_panel.py are the entry points, one per
pill. panel.py tells panels apart by script name, which is why each pill gets
a file of its own rather than an argument.
"""

import os
import shlex
import subprocess
import sys
import threading
import time

import cairo
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import memory  # noqa: E402
import panelui  # noqa: E402
from proctable import ProcTable  # noqa: E402
import themecolors  # noqa: E402

HIST_DIR = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "waybar-sensors")
POLL_MS = 2000
GPU_PROCS_EVERY = 2         # nvidia-smi is ~50ms, so the GPU list every 2nd poll

# Graph colours: the desktop theme's color.cpu / color.gpu (theme.conf ->
# generated/colors.conf, see themecolors.py), cyberpunk's as the fallback --
# the same colours as the CPU / GPU labels on the bar.
MAGENTA = themecolors.rgb("cpu", "#ff2a6d")
GREEN = themecolors.rgb("gpu", "#39ff14")

GRAPH_W, GRAPH_H = 230, 30   # Graph's default (weather and network panels)
# The CPU/GPU panels use a compact graph: a sparkline's job is the shape of
# the last five minutes, which reads fine at this size, and the panel opens
# under a pill where a tall card covers a lot of whatever is below.
COMPACT_W, COMPACT_H = 160, 16
PROC_ROWS = 4               # the CPU's "TOP CPU" list, in its own column
APP_ROWS = 6                # rows in the memory app table
GPU_APP_ROWS = 10           # the GPU's table has the whole right column
# The card height is panelui.CARD_HEIGHT, shared with the network card. The
# GPU card's graphs stretch to fill it (Section rows are vexpand) and its app
# table gets more rows.
# Clearing swap moves everything in it back into RAM; with less free than
# that, swapoff makes the kernel kill processes instead. Only offered while
# available RAM covers the swap in use plus this much to spare.
SWAP_HEADROOM = 1 << 30
SWAP_ARM_SECONDS = 4
SWAP_RESULT_SECONDS = 8


def swap_devices(path="/proc/swaps"):
    """[(device, priority)] of the swap in use now. Fedora's is zram, which is
    not in fstab, so `swapon -a` would never bring it back: each one is turned
    off and on again by name, with the priority it had."""
    found = []
    try:
        with open(path) as handle:
            for line in handle.readlines()[1:]:
                parts = line.split()
                if len(parts) >= 5:
                    found.append((parts[0].replace("\\040", " "), int(parts[4])))
    except (OSError, ValueError):
        pass
    return found


def swap_clear_cmd(devices):
    """One pkexec (one password) for all of them: off, then on again."""
    steps = []
    for dev, prio in devices:
        on = f"swapon -p {prio} {shlex.quote(dev)}" if prio >= 0 else f"swapon {shlex.quote(dev)}"
        steps.append(f"swapoff {shlex.quote(dev)} && {on}")
    return ["pkexec", "sh", "-c", " && ".join(steps)] if steps else None


def read_hist(name):
    """List of rows (lists of floats), oldest first. A row the writer was
    halfway through is simply skipped."""
    rows = []
    try:
        with open(os.path.join(HIST_DIR, name + ".hist")) as fh:
            for line in fh:
                try:
                    rows.append([float(x) for x in line.split()])
                except ValueError:
                    pass
    except OSError:
        pass
    return rows


class TopCpu:
    """Top processes by CPU *right now*: per-process CPU time from
    /proc/<pid>/stat, differenced between two calls. `ps -o pcpu` is not used
    because it is a lifetime average -- a process that just started reads as
    90% (this panel included), and one that was busy an hour ago still shows.
    The first call has nothing to difference against and returns [].
    Percent is of one core, like top."""

    TICK = os.sysconf("SC_CLK_TCK")

    def __init__(self):
        self.prev, self.when = {}, None
        self.me = os.getpid()

    @staticmethod
    def sample():
        out = {}
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                with open(f"/proc/{pid}/stat") as fh:
                    raw = fh.read()
            except OSError:
                continue
            # comm is in parentheses and may itself contain spaces or ')'.
            name = raw[raw.index("(") + 1:raw.rindex(")")]
            fields = raw[raw.rindex(")") + 2:].split()
            out[int(pid)] = (name, int(fields[11]) + int(fields[12]))
        return out

    def __call__(self, n=PROC_ROWS):
        now = GLib.get_monotonic_time() / 1e6
        cur = self.sample()
        rows = []
        if self.when is not None:
            elapsed = max(now - self.when, 1e-3)
            for pid, (name, ticks) in cur.items():
                before = self.prev.get(pid)
                if pid == self.me or not before or before[0] != name:
                    continue
                pct = 100.0 * (ticks - before[1]) / self.TICK / elapsed
                if pct > 0.05:
                    rows.append((pct, name))
        self.prev, self.when = cur, now
        rows.sort(reverse=True)
        return [(f"{pct:5.1f}%", name) for pct, name in rows[:n]]


class Graph(Gtk.DrawingArea):
    """A sparkline. lo/hi are the fixed scale; hi=None means auto-scale to the
    largest value seen (used for power, which has no natural ceiling).

    The time axis is fixed too: `capacity` samples always span the full width,
    newest at the right edge. With less history than that the line simply
    starts part-way across -- stretching six samples over the whole graph
    would make ten seconds look like five minutes."""

    def __init__(self, colour, lo=0.0, hi=100.0, capacity=60,
                 size=(GRAPH_W, GRAPH_H)):
        super().__init__()
        self.colour, self.lo, self.hi = colour, lo, hi
        self.capacity = capacity
        self.values = []
        self.set_size_request(*size)
        self.connect("draw", self.on_draw)

    def set_values(self, values):
        self.values = values
        self.queue_draw()

    def on_draw(self, _widget, cr):
        w = self.get_allocated_width()
        h = self.get_allocated_height()
        r, g, b = self.colour

        # Floor and two faint grid lines at 1/3 and 2/3.
        cr.set_source_rgba(r, g, b, 0.05)
        cr.rectangle(0, 0, w, h)
        cr.fill()
        cr.set_source_rgba(r, g, b, 0.10)
        cr.set_line_width(1)
        for frac in (1 / 3, 2 / 3):
            y = int(h * frac) + 0.5
            cr.move_to(0, y)
            cr.line_to(w, y)
        cr.stroke()

        vals = self.values[-self.capacity:]
        if len(vals) < 2:
            return False
        hi = self.hi if self.hi is not None else max(max(vals) * 1.15, 1.0)
        span = max(hi - self.lo, 1e-6)
        step = w / (self.capacity - 1)
        x0 = w - (len(vals) - 1) * step          # newest sample on the right edge

        def point(i, v):
            frac = min(max((v - self.lo) / span, 0.0), 1.0)
            return x0 + i * step, h - 1 - frac * (h - 3)

        # Filled area, fading towards the floor.
        cr.move_to(x0, h)
        for i, v in enumerate(vals):
            cr.line_to(*point(i, v))
        cr.line_to(w, h)
        cr.close_path()
        grad = cairo.LinearGradient(0, 0, 0, h)
        grad.add_color_stop_rgba(0, r, g, b, 0.35)
        grad.add_color_stop_rgba(1, r, g, b, 0.02)
        cr.set_source(grad)
        cr.fill()

        # The line, twice: wide and faint for the glow, thin and bright on top.
        for width, alpha in ((4, 0.25), (1.4, 1.0)):
            cr.set_source_rgba(r, g, b, alpha)
            cr.set_line_width(width)
            cr.move_to(*point(0, vals[0]))
            for i, v in enumerate(vals[1:], 1):
                cr.line_to(*point(i, v))
            cr.stroke()
        return False


def gpu_apps(n=APP_ROWS):
    """Every process on the GPU from `nvidia-smi pmon` (graphics AND compute,
    unlike --query-compute-apps), grouped by name: summed SM % (its share of
    the GPU's compute over the last sample) and framebuffer MB."""
    try:
        out = subprocess.run(["nvidia-smi", "pmon", "-c", "1", "-s", "um"],
                             capture_output=True, text=True, timeout=3).stdout
    except (subprocess.SubprocessError, OSError):
        return []
    apps = {}
    for line in out.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        f = line.split()
        if len(f) < 12:
            continue
        try:
            pid = int(f[1])
        except ValueError:
            continue
        sm = int(f[3]) if f[3].isdigit() else 0
        fb = int(f[9]) if f[9].isdigit() else 0
        name = " ".join(f[11:])
        app = apps.setdefault(name, {"name": name, "sm": 0, "fb": 0, "pids": []})
        app["sm"] += sm
        app["fb"] += fb
        app["pids"].append(pid)
    ranked = sorted(apps.values(), key=lambda a: (-a["sm"], -a["fb"]))[:n]
    return [{"name": a["name"], "pids": a["pids"],
             "values": [f"{a['sm']}%" if a["sm"] else "-",
                        f"{a['fb'] / 1024:.1f}G" if a["fb"] >= 1024 else f"{a['fb']}M"]}
            for a in ranked]


def memory_apps(n=APP_ROWS):
    return [{"name": a["name"], "pids": a["pids"],
             "values": [f"{len(a['pids'])}" if len(a["pids"]) > 1 else "",
                        memory.human(a["size"])]}
            for a in memory.apps(n)]


def level_bar(percent):
    bar = Gtk.LevelBar(min_value=0, max_value=100, value=min(percent, 100))
    bar.set_mode(Gtk.LevelBarMode.CONTINUOUS)
    for offset in ("low", "high", "full"):
        bar.remove_offset_value(offset)
    style = bar.get_style_context()
    style.add_class("dk-bar")
    if percent >= 95:
        style.add_class("critical")
    elif percent >= 85:
        style.add_class("warning")
    bar.set_size_request(COMPACT_W, -1)
    bar.set_valign(Gtk.Align.CENTER)
    return bar


def heading_label(text):
    label = Gtk.Label(label=text)
    label.get_style_context().add_class("kb-heading")
    label.set_xalign(0)
    return label


class MemorySection:
    """RAM and swap bars, the pressure line, and the app table."""

    def __init__(self):
        self.widget = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.widget.get_style_context().add_class("sn-section")
        head = Gtk.Label(label="MEMORY")
        head.get_style_context().add_class("kb-heading")
        head.set_xalign(0)
        self.widget.pack_start(head, False, False, 0)
        self.stats = Gtk.Grid(column_spacing=8, row_spacing=2)
        self.widget.pack_start(self.stats, False, False, 0)
        # Not packed here: Sensors puts the table in the right-hand column.
        self.table = ProcTable(["procs", "RAM"], on_ended=self.update)
        self.apps_busy = False
        self.swap_armed = 0.0
        self.swap_clearing = False
        self.swap_result = ""
        self.swap_total = 0         # while clearing, SwapTotal reads 0: the row stays

    def update(self):
        r = memory.reading()
        if r["swap_total"]:
            self.swap_total = r["swap_total"]
        elif self.swap_clearing and self.swap_total:
            r = dict(r, swap_total=self.swap_total, swap_used=self.swap_left())
        for child in self.stats.get_children():
            self.stats.remove(child)
        rows = [("RAM", r["used"], r["total"],
                 f"{memory.human(r['used'])} / {memory.human(r['total'])}")]
        if r["swap_total"]:
            rows.append(("SWAP", r["swap_used"], r["swap_total"],
                         f"{memory.human(r['swap_used'])} / {memory.human(r['swap_total'])}"))
        for i, (name, used, total, text) in enumerate(rows):
            lab = Gtk.Label(label=name)
            lab.get_style_context().add_class("sn-label")
            lab.set_xalign(0)
            self.stats.attach(lab, 0, i, 1, 1)
            self.stats.attach(level_bar(100 * used / max(total, 1)), 1, i, 1, 1)
            value = Gtk.Label(label=text)
            value.get_style_context().add_class("sn-value")
            value.set_xalign(1)
            value.set_hexpand(True)
            self.stats.attach(value, 2, i, 1, 1)
            if name == "SWAP":
                self.stats.attach(self.swap_button(r), 3, i, 1, 1)
        if r["some"]:
            text = f"pressure: tasks waited {r['some']:.1f}% of the last 10 s"
            if r["full"]:
                text += f", all stalled {r['full']:.1f}%"
        else:
            text = f"pressure: none  \u00b7  {memory.human(r['cached'])} cache the kernel can drop"
        if self.swap_clearing:
            text = (f"clearing swap: {memory.human(r['swap_used'])} still to move back into RAM"
                    if r["swap_used"] else "clearing swap: turning it back on")
        elif self.swap_result:
            text = self.swap_result
        note = Gtk.Label(label=text)
        note.get_style_context().add_class("ctl-sub")
        note.set_xalign(0)
        self.stats.attach(note, 0, len(rows), 4, 1)
        self.stats.show_all()
        self.refresh_apps()

    def refresh_apps(self):
        """PSS is slow to read (memory.py), so the table is filled from a
        thread; a second call while one is still running is dropped."""
        if self.apps_busy:
            return
        self.apps_busy = True

        def work():
            rows = memory_apps()
            GLib.idle_add(done, rows)

        def done(rows):
            self.apps_busy = False
            self.table.set(rows)
            return False
        threading.Thread(target=work, daemon=True).start()


    # -- clearing swap ---------------------------------------------------------
    def swap_button(self, r):
        armed = time.monotonic() - self.swap_armed < SWAP_ARM_SECONDS
        fits = r["available"] >= r["swap_used"] + SWAP_HEADROOM
        text = "Clearing..." if self.swap_clearing else ("Sure?" if armed else "Clear")
        button = Gtk.Button(label=text)
        button.get_style_context().add_class("dev-pick")
        button.set_valign(Gtk.Align.CENTER)
        button.set_sensitive(fits and not self.swap_clearing)
        if not fits:
            button.set_tooltip_text(
                f"Needs {memory.human(r['swap_used'] + SWAP_HEADROOM)} of free RAM "
                f"to take the swap back; {memory.human(r['available'])} is free")
        else:
            button.set_tooltip_text("Move swap back into RAM (swapoff + swapon, asks for your password)")
        if armed and not self.swap_clearing:
            button.get_style_context().add_class("active")
            button.get_child().set_markup(f"<span foreground='{themecolors.hex('danger', '#ff2a6d')}'>Sure?</span>")
        button.connect("clicked", lambda _b: self.clear_swap())
        return button

    def swap_left(self):
        """While swapoff runs, what is still in the device(s) being emptied:
        /proc/swaps keeps the line, with its Used column going down."""
        used = 0
        try:
            with open("/proc/swaps") as handle:
                for line in handle.readlines()[1:]:
                    used += int(line.split()[3]) * 1024
        except (OSError, ValueError, IndexError):
            pass
        return used

    def clear_swap(self):
        if time.monotonic() - self.swap_armed >= SWAP_ARM_SECONDS:
            self.swap_armed = time.monotonic()
            self.update()
            GLib.timeout_add(SWAP_ARM_SECONDS * 1000, lambda: (self.update(), False)[1])
            return
        self.swap_armed = 0.0
        cmd = swap_clear_cmd(swap_devices())
        before = memory.reading()["swap_used"]
        if not cmd:
            self.swap_result = "no swap is on"
            self.update()
            return
        self.swap_clearing = True
        self.swap_result = ""
        self.update()

        def work():
            try:
                out = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
                ok = out.returncode == 0
                # pkexec exits 126 when the password prompt is dismissed.
                msg = (f"swap cleared: {memory.human(before)} moved back into RAM" if ok else
                       "cancelled" if out.returncode == 126 else
                       f"swapoff failed: {(out.stderr or '').strip()[:60]}")
            except (OSError, subprocess.SubprocessError) as exc:
                msg = f"swapoff failed: {exc}"
            GLib.idle_add(done, msg)

        def done(msg):
            self.swap_clearing = False
            self.swap_result = msg
            self.update()
            GLib.timeout_add(SWAP_RESULT_SECONDS * 1000,
                             lambda: (setattr(self, "swap_result", ""), self.update(), False)[2])
            return False
        threading.Thread(target=work, daemon=True).start()


class Section:
    """Heading (with an optional link on the right), one row per metric
    (label | graph | value), then a short process list."""

    def __init__(self, title, colour, metrics, link=None):
        self.metrics = metrics          # [(label, column, lo, hi, fmt[, hint])]
        # hint: the tooltip on a value that has no data yet -- says why.
        self.hints = {m[0]: m[5] for m in metrics if len(m) > 5}
        self.widget = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.widget.get_style_context().add_class("sn-section")
        self.widget.get_style_context().add_class("sn-compact")

        # The link (htop / nvtop) shares the heading's line instead of taking
        # a row of its own at the bottom of the card.
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        head = Gtk.Label(label=title)
        head.get_style_context().add_class("kb-heading")
        head.set_xalign(0)
        top.pack_start(head, True, True, 0)
        if link is not None:
            top.pack_end(link, False, False, 0)
        self.widget.pack_start(top, False, False, 0)

        # The graphs stretch to the height of the card: the process column on
        # the right sets it, and the rows share whatever is left equally
        # (row_homogeneous) instead of leaving a gap under thin sparklines.
        grid = Gtk.Grid()
        grid.set_column_spacing(8)
        grid.set_row_spacing(6)
        grid.set_row_homogeneous(True)
        grid.set_vexpand(True)
        self.graphs, self.values = [], []
        for row, (label, _col, lo, hi, _fmt, *_extra) in enumerate(metrics):
            name = Gtk.Label(label=label)
            name.get_style_context().add_class("sn-label")
            name.set_xalign(0)
            grid.attach(name, 0, row, 1, 1)

            graph = Graph(colour, lo, hi, size=(COMPACT_W, COMPACT_H))
            graph.set_vexpand(True)
            grid.attach(graph, 1, row, 1, 1)
            self.graphs.append(graph)

            value = Gtk.Label(label="–")
            value.get_style_context().add_class("sn-value")
            value.set_xalign(1)
            value.set_width_chars(5)
            grid.attach(value, 2, row, 1, 1)
            self.values.append(value)
        self.widget.pack_start(grid, True, True, 0)

        self.status = Gtk.Label(label="")
        self.status.get_style_context().add_class("ctl-sub")
        self.status.set_xalign(0)
        self.widget.pack_start(self.status, False, False, 0)

        self.procs = Gtk.Label(label="")
        self.procs.get_style_context().add_class("sn-procs")
        self.procs.set_xalign(0)
        self.widget.pack_start(self.procs, False, False, 0)

    def update(self, rows):
        if not rows:
            self.status.set_text("No history yet — reload the bar (ALT+G).")
            self.status.show()
        else:
            self.status.hide()
        for graph, value, (_label, col, _lo, _hi, fmt, *_extra) in zip(
                self.graphs, self.values, self.metrics):
            series = [r[col] for r in rows if len(r) > col]
            graph.set_values(series)
            value.set_text(fmt.format(series[-1]) if series else "–")
            hint = self.hints.get(_label)
            value.set_tooltip_text(hint if hint and not series else None)

    def set_procs(self, rows):
        self.procs.set_text("\n".join(f"{a}  {b}" for a, b in rows))


class Sensors(panelui.Panel):
    """One device per panel: KIND picks which. Each pill opens its own panel
    (cpu_panel.py / gpu_panel.py), so the graph comes up directly under the
    pill that was clicked rather than one shared panel under whichever."""

    KIND = None

    # Columns in the .hist lines: 0 epoch, then as written by the scripts.
    SPECS = {
        "cpu": ("CPU", MAGENTA, [
            ("LOAD", 1, 0, 100, "{:.0f}%"),
            ("TEMP", 2, 20, 100, "{:.0f}°C"),
            ("RAM",  3, 0, 100, "{:.0f}%"),
            # Package power, from /run/cpu-power/watts via cpu_usage.sh --
            # only there while a root service publishes it (RAPL is root-only).
            ("POWER", 4, 0, None, "{:.0f}W",
             "CPU power is root-only (RAPL): it shows up here once a root "
             "service writes a 5 s average in watts to /run/cpu-power/watts"),
        ], ("htop", ["kitty", "-e", "htop", "--sort-key", "PERCENT_CPU"])),
        "gpu": ("GPU", GREEN, [
            ("LOAD", 1, 0, 100, "{:.0f}%"),
            ("TEMP", 2, 20, 100, "{:.0f}°C"),
            ("VRAM", 3, 0, 100, "{:.0f}%"),
            ("POWER", 4, 0, None, "{:.0f}W"),
        ], ("nvtop", ["kitty", "-e", "nvtop"])),
    }

    def build(self):
        title, colour, metrics, (label, cmd) = self.SPECS[self.KIND]
        button = Gtk.Button(label=label)
        button.get_style_context().add_class("ctl-link")
        button.get_style_context().add_class("sn-link")
        button.set_valign(Gtk.Align.START)
        button.connect("clicked", lambda _b: self.launch(cmd))
        self.section = Section(title, colour, metrics, link=button)
        self.card.set_size_request(-1, panelui.CARD_HEIGHT)
        left, right = panelui.columns(self.card)
        left.pack_start(self.section.widget, True, True, 0)

        self.ticks = 0
        if self.KIND == "cpu":
            # Baseline now; the first real list comes at the first poll, since
            # the moment between build() and on_ready() is too short to rank.
            self.top = TopCpu()
            self.top()
            sep = Gtk.Separator()
            sep.get_style_context().add_class("ctl-sep")
            left.pack_start(sep, False, False, 0)
            self.memory = MemorySection()
            left.pack_start(self.memory.widget, False, False, 0)
            # Right: what is using the CPU now, then what is using the RAM.
            self.section.widget.remove(self.section.procs)
            right.pack_start(heading_label("TOP CPU"), False, False, 0)
            right.pack_start(self.section.procs, False, False, 0)
            right.pack_start(heading_label("APPS BY MEMORY"), False, False, 0)
            right.pack_start(self.memory.table.widget, False, False, 0)
        else:
            # The GPU's app table replaces the two-line VRAM list.
            self.top = None
            self.gpu_table = ProcTable(["GPU", "VRAM"], on_ended=self.refresh_gpu)
            right.pack_start(heading_label("APPS ON THE GPU"), False, False, 0)
            right.pack_start(self.gpu_table.widget, False, False, 0)

    def refresh_gpu(self):
        self.gpu_table.set(gpu_apps(GPU_APP_ROWS))

    def on_ready(self):
        # First fill here, not in build(): panelui calls show_all() after
        # build(), which would re-show the "no history" note even when hidden.
        self.section.update(read_hist(self.KIND))
        if self.KIND == "gpu":
            self.refresh_gpu()
        else:
            self.memory.update()
        GLib.timeout_add(POLL_MS, self.poll)

    def poll(self):
        self.section.update(read_hist(self.KIND))
        # /proc reads are cheap: every poll. nvidia-smi is ~80ms: every other.
        if self.KIND == "cpu":
            self.section.set_procs(self.top())
            self.memory.update()
        elif self.ticks % GPU_PROCS_EVERY == 0:
            self.refresh_gpu()
        self.ticks += 1
        return True

    def launch(self, cmd):
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        self.quit()


def main(kind):
    panel = type(f"{kind.title()}Sensors", (Sensors,), {"KIND": kind})
    panelui.run(panel)
