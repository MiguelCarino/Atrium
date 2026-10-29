#!/usr/bin/env python3
"""Live picture-in-picture: a small always-on-top copy of a window or of a
piece of the screen, updating as it changes.

    pip.py window            mirror the focused window
    pip.py window --pick     ... or click the one to mirror
    pip.py region            draw a rectangle (slurp), mirror what is in it
    pip.py toggle            close the mirror if one is up, else `window`
    pip.py close             close it
    pip.py status [--json]   what is mirrored now
    pip.py get [--json]      the settings
    pip.py set KEY VALUE     change one (see DEFAULTS / LIMITS)

One mirror at a time: a new one replaces the old. Closing the mirror window
(q in it, or ALT+Q) ends everything; so does the source window closing.

HOW EACH ONE IS CAPTURED

    region   gpu-screen-recorder grabs the rectangle off the screen (KMS,
             the card's encoder -- NVENC on NVIDIA, VAAPI on AMD and Intel,
             x264 on the CPU where gpu.py's encoder() finds none: the same
             recorder and choice as record.sh), at `fps`, as an H.264
             MPEG-TS stream on a pipe straight into mpv, which decodes it on
             the card (hwdec) with its low-latency profile. A few % of one
             core all told; ~100-200 ms behind the screen.
    window   grim -T, the toplevel-capture protocol: grim asks the
             compositor for that one window's picture, whatever is in front
             of it, so the mirror is the window alone. One PPM frame per
             call, `window_fps` times a second, piped into mpv. grim takes
             ~25 ms a frame for a 1700x1400 window, mostly the copy off the
             card, so this is kept at a modest rate (default 10 fps). There
             is no Wayland video stream of a single window without the
             screen-share portal (a picker dialog every time), and
             gpu-screen-recorder's window capture is X11 only.

A WINDOW ON ANOTHER WORKSPACE. Works with `window`: grim -T capture does not
need the window to be on screen (tested: a Chrome window on a hidden
workspace came back whole). What it shows is the last picture the app drew,
though -- many apps (browsers above all) stop painting while they are not
visible, so a hidden window's mirror may sit still until it is shown again.
`region` mirrors a place on the screen, so it shows whatever is there now.

The mirror window is mpv with app id desktop.pip and its own config
(--no-config: none of the user's mpv.conf, uosc or keys but q to quit).
lua/pip.lua's rules float it, pin it to every workspace, keep it from
taking the focus and drop its border; pip.py then sizes it to `width` (the
source's aspect ratio kept) and parks it in `corner` of the focused screen.
ALT+right-drag resizes it, ALT+left-drag moves it, as any floating window.

passthrough=on: clicks go through the mirror to what is under it. A Hyprland
window cannot be made click-through (0.56 has no window rule for it --
checked), so in this mode the mirror is not mpv but a GTK layer-shell strip,
like the OSD and the captions: fed by grim (also for a region), drawn by
GTK, fixed in its corner. It cannot be moved or resized by hand then;
`width` and `corner` say where it goes. Layer surfaces belong to a screen,
not a workspace, so it shows on every workspace of that screen.

Settings, ~/.local/state/hypr/pip.conf (key=value, a missing key is its
default):
    width        240-1600  px, the long side of the mirror
    corner       bottom-right | bottom-left | top-right | top-left
    opacity      30-100    %  (lua/pip.lua applies it; GTK in passthrough)
    fps          5-60      a region's frame rate
    window_fps   2-30      a window's frame rate
    passthrough  on | off
"""
import json
import os
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import desk_common  # noqa: E402  (hypr_request: hyprctl over the socket)
NOTIFY = os.path.join(HERE, "notify")  # notify-send with the theme's mascot (mascot_notify.py)
SELF = os.path.abspath(__file__)
RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
PIDFILE = os.path.join(RUNTIME, "pip.json")
CONF = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "hypr", "pip.conf")
APP_ID = "desktop.pip"
MARGIN = 24                     # from the screen's edges (the bar is in the top one)
BAR_H = 44                      # a top corner stays clear of the bar

DEFAULTS = {"width": "480", "corner": "bottom-right", "opacity": "100", "fps": "30", "window_fps": "10",
            "passthrough": "off"}
LIMITS = {"width": (240, 1600), "opacity": (30, 100), "fps": (5, 60), "window_fps": (2, 30)}
CHOICES = {"corner": ("bottom-right", "bottom-left", "top-right", "top-left"), "passthrough": ("on", "off")}


# -- settings ---------------------------------------------------------------------------
def check_value(key, value):
    value = str(value).strip().lower()
    if key in CHOICES:
        return value if value in CHOICES[key] else None
    if key in LIMITS:
        try:
            n = int(value)
        except ValueError:
            return None
        lo, hi = LIMITS[key]
        return str(n) if lo <= n <= hi else None
    return None


def read_settings(path=None):
    values = dict(DEFAULTS)
    try:
        with open(path or CONF) as handle:
            for line in handle:
                key, sep, value = line.strip().partition("=")
                if sep and key in DEFAULTS and check_value(key, value) is not None:
                    values[key] = check_value(key, value)
    except OSError:
        pass
    return values


def write_setting(key, value, path=None):
    path = path or CONF
    norm = check_value(key, value) if key in DEFAULTS else None
    if norm is None:
        if key not in DEFAULTS:
            raise ValueError(f"unknown setting {key!r} (one of: {', '.join(DEFAULTS)})")
        raise ValueError(f"{key} must be " + ("|".join(CHOICES[key]) if key in CHOICES else "%d-%d" % LIMITS[key]))
    values = read_settings(path)
    values[key] = norm
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w") as handle:
        handle.writelines(f"{k}={v}\n" for k, v in values.items() if v != DEFAULTS[k])
    os.replace(path + ".tmp", path)
    return norm


# -- geometry (pure) ---------------------------------------------------------------------
def fit(src_w, src_h, width):
    """The mirror's size: `width` on the long side, the source's shape kept."""
    src_w, src_h = max(1, src_w), max(1, src_h)
    if src_w >= src_h:
        return width, max(1, round(width * src_h / src_w))
    return max(1, round(width * src_w / src_h)), width


def logical(mon):
    """(x, y, w, h) of a hyprctl monitor in layout coordinates."""
    w, h = mon["width"] / mon["scale"], mon["height"] / mon["scale"]
    if mon.get("transform", 0) % 2 == 1:
        w, h = h, w
    return mon["x"], mon["y"], int(w), int(h)


def place(mon, size, corner):
    """Top-left of a SIZE window in CORNER of hyprctl monitor MON."""
    x, y, w, h = logical(mon)
    ww, wh = size
    left = x + MARGIN if corner.endswith("left") else x + w - ww - MARGIN
    top = y + MARGIN + BAR_H if corner.startswith("top") else y + h - wh - MARGIN
    return int(left), int(top)


def window_boxes(clients, monitors):
    """slurp's predefined rectangles for the windows one can click: those on
    a workspace some screen shows now, and pinned ones; the mirror itself
    left out. Lines of "X,Y WxH stableId"."""
    shown = {m["activeWorkspace"]["id"] for m in monitors}
    shown |= {m.get("specialWorkspace", {}).get("id") for m in monitors} - {0, None}
    lines = []
    for c in clients:
        if c.get("class") == APP_ID or not c.get("mapped", True) or c.get("hidden"):
            continue
        if c["workspace"]["id"] in shown or c.get("pinned"):
            (x, y), (w, h) = c["at"], c["size"]
            lines.append(f"{x},{y} {w}x{h} {c['stableId']}")
    return lines


def parse_slurp(text):
    """slurp's default "X,Y WxH" -> (x, y, w, h); None on a cancel."""
    try:
        pos, size = text.split()[:2]
        x, y = (int(v) for v in pos.split(","))
        w, h = (int(v) for v in size.split("x"))
    except ValueError:
        return None
    return (x, y, w, h) if w > 1 and h > 1 else None


def gsr_argv(region, fps, encoder="gpu"):
    """The recorder for a region. encoder: gpu.py's pick ("gpu" or "cpu";
    capture_encoder()): with "cpu" gsr is told -encoder cpu (x264), since
    its default, the card, would fail where there is no hardware encoder."""
    x, y, w, h = region
    w, h = w - w % 2, h - h % 2         # H.264 wants even sizes
    return ["gpu-screen-recorder", "-w", f"{w}x{h}+{x}+{y}", "-f", str(fps), "-c", "mpegts", "-k", "h264",
            "-q", "high", "-cursor", "yes"] + (["-encoder", "cpu"] if encoder == "cpu" else []) + \
        ["-o", "/dev/stdout"]


def capture_encoder():
    """"gpu" or "cpu": gpu.py's encoder() (gsr --info, cached for the boot);
    "gpu" -- gsr's own default -- when that cannot be asked."""
    try:
        sys.path.insert(0, HERE)
        import gpu
        return gpu.encoder().get("encoder") or "gpu"
    except Exception:  # noqa: BLE001 -- the old behaviour is the safe guess
        return "gpu"


def mpv_argv(title, size, fmt=None):
    argv = ["mpv", "--no-config", "--really-quiet", "--profile=low-latency", "--untimed", "--cache=no",
            "--hwdec=auto-safe", "--no-audio", "--osc=no", "--osd-level=0", "--keepaspect-window=yes",
            "--no-input-cursor", "--cursor-autohide=always", f"--wayland-app-id={APP_ID}", f"--title={title}",
            f"--geometry={size[0]}x{size[1]}", "--force-window=immediate", "--background-color=#000000"]
    if fmt:
        # low-latency's probe-info=nostreams leaves ppm_pipe without a
        # stream ("Invalid data found") -- tested; the rest of it is fine.
        argv += ["--demuxer=lavf", f"--demuxer-lavf-format={fmt}", "--demuxer-lavf-probe-info=auto"]
    return argv + ["-"]


# -- the compositor --------------------------------------------------------------------
def hypr_json(*what):
    """`hyprctl ARGS -j`, parsed; None when Hyprland does not answer. Over the
    request socket (desk_common.hypr_request): no process."""
    return desk_common.hypr_request(what, json=True, timeout=3)


def focused_monitor():
    mons = hypr_json("monitors") or []
    return next((m for m in mons if m.get("focused")), mons[0] if mons else None)


def hypr_eval(code):
    subprocess.run(["hyprctl", "eval", code], capture_output=True, timeout=3)


def notify(title, body=""):
    subprocess.run([NOTIFY, "-a", "Picture-in-picture", "-u", "low", "-t", "3000", title, body],
                   capture_output=True)


# -- the running mirror ------------------------------------------------------------------
def running():
    """The live mirror's record from the pid file, or None."""
    try:
        with open(PIDFILE) as handle:
            info = json.load(handle)
        with open(f"/proc/{info['pid']}/cmdline", "rb") as handle:
            if b"pip.py" not in handle.read():
                return None
        return info
    except (OSError, ValueError, KeyError, TypeError):
        return None


def close():
    info = running()
    if not info:
        return False
    try:
        os.kill(info["pid"], signal.SIGTERM)
    except OSError:
        return False
    for _ in range(30):             # until it has cleaned up, so a new one can start
        if not running():
            break
        time.sleep(0.05)
    return True


def start(mode, args):
    """Pick the source here (the slurp / the focused window), then hand off
    to a detached supervisor (`pip.py run ...`) and return."""
    if mode == "window":
        if "--pick" in args:
            boxes = window_boxes(hypr_json("clients") or [], hypr_json("monitors") or [])
            res = subprocess.run(["slurp", "-r", "-f", "%l"], input="\n".join(boxes), capture_output=True, text=True)
            ident = res.stdout.strip()
            if res.returncode != 0 or not ident:
                return
        else:
            active = hypr_json("activewindow") or {}
            if not active.get("stableId"):
                notify("Nothing to mirror", "No window has the focus.")
                return
            if active.get("class") == APP_ID:
                close()             # the mirror itself is focused: the key closes it
                return
            ident = active["stableId"]
        client = next((c for c in hypr_json("clients") or [] if c.get("stableId") == ident), None)
        if not client:
            return
        source = {"mode": "window", "id": ident, "w": client["size"][0], "h": client["size"][1],
                  "title": client.get("title") or client.get("class", "")}
    else:
        res = subprocess.run(["slurp", "-d"], capture_output=True, text=True)
        region = parse_slurp(res.stdout) if res.returncode == 0 else None
        if not region:
            return
        source = {"mode": "region", "region": region, "w": region[2], "h": region[3],
                  "title": "{2}x{3} at {0},{1}".format(*region)}
    close()
    subprocess.Popen([sys.executable, SELF, "run", json.dumps(source)], start_new_session=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def supervise(source):
    """The detached half: the capture, the viewer, the pid file; ends when
    either end stops or on SIGTERM (pip.py close)."""
    settings = read_settings()
    size = fit(source["w"], source["h"], int(settings["width"]))
    mon = focused_monitor()
    procs = []
    with open(PIDFILE + ".tmp", "w") as handle:
        json.dump({"pid": os.getpid(), **source, "started": time.time()}, handle)
    os.replace(PIDFILE + ".tmp", PIDFILE)

    def finish(*_):
        for p in procs:
            try:
                p.terminate()
            except OSError:
                pass
        for p in procs:
            try:
                p.wait(2)
            except subprocess.SubprocessError:
                p.kill()
        try:
            if json.load(open(PIDFILE)).get("pid") == os.getpid():
                os.unlink(PIDFILE)
        except (OSError, ValueError):
            pass
        os._exit(0)

    signal.signal(signal.SIGTERM, finish)
    signal.signal(signal.SIGINT, finish)

    if settings["passthrough"] == "on":
        viewer_gtk(source, size, mon, settings)
        finish()

    hypr_eval('require("lua.pip").apply()')        # the rules exist even without the require line
    title = f"PiP · {source['title']}"[:80]
    if source["mode"] == "region":
        capture = subprocess.Popen(gsr_argv(source["region"], settings["fps"], capture_encoder()),
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL)
        procs.append(capture)
        viewer = subprocess.Popen(mpv_argv(title, size), stdin=capture.stdout, stderr=subprocess.DEVNULL)
        capture.stdout.close()                     # mpv holds the pipe now
        procs.insert(0, viewer)
        threading_place(viewer.pid, size, mon, settings["corner"])
        while viewer.poll() is None and capture.poll() is None:
            time.sleep(0.5)
        finish()

    viewer = subprocess.Popen(mpv_argv(title, size, "ppm_pipe"), stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
    procs.append(viewer)
    threading_place(viewer.pid, size, mon, settings["corner"])
    period, misses = 1 / int(settings["window_fps"]), 0
    while viewer.poll() is None:
        t = time.monotonic()
        # grim writes straight into mpv's pipe: 7 MB a frame for a big
        # window never passes through Python (that copy cost ~3x grim itself).
        res = subprocess.run(grim_argv(source), stdout=viewer.stdin, stderr=subprocess.DEVNULL)
        if res.returncode != 0:
            misses += 1
            if misses >= 5 or viewer.poll() is not None:     # the window is gone, or the mirror closed
                break
        else:
            misses = 0
        time.sleep(max(0.0, period - (time.monotonic() - t)))
    finish()


def threading_place(pid, size, mon, corner):
    """Once mpv's window is mapped: its size and corner (in a thread, so the
    first frames are not held up)."""
    import threading

    def go():
        for _ in range(100):
            client = next((c for c in hypr_json("clients") or [] if c.get("pid") == pid), None)
            if client:
                x, y = place(mon, size, corner) if mon else (0, 0)
                target = f'"address:{client["address"]}"'
                hypr_eval(f"hl.dispatch(hl.dsp.window.resize({{ x = {size[0]}, y = {size[1]}, window = {target} }})); "
                          f"hl.dispatch(hl.dsp.window.move({{ x = {x}, y = {y}, window = {target} }}))")
                return
            time.sleep(0.05)
    threading.Thread(target=go, daemon=True).start()


# -- passthrough: the GTK layer-shell viewer ----------------------------------------------
def parse_ppm(data):
    """(width, height, rgb bytes) of a binary PPM (P6, maxval 255)."""
    fields, pos = [], 0
    while len(fields) < 4:
        while data[pos:pos + 1].isspace():
            pos += 1
        if data[pos:pos + 1] == b"#":
            pos = data.index(b"\n", pos) + 1
            continue
        end = pos
        while not data[end:end + 1].isspace():
            end += 1
        fields.append(data[pos:end])
        pos = end
    if fields[0] != b"P6" or fields[3] != b"255":
        raise ValueError("not an 8-bit P6 PPM")
    w, h = int(fields[1]), int(fields[2])
    return w, h, data[pos + 1:pos + 1 + w * h * 3]


def grim_argv(source):
    if source["mode"] == "window":
        return ["grim", "-T", source["id"], "-t", "ppm", "-"]
    x, y, w, h = source["region"]
    return ["grim", "-g", f"{x},{y} {w}x{h}", "-t", "ppm", "-"]


def viewer_gtk(source, size, mon, settings):
    import threading
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, GtkLayerShell
    import cairo

    win = Gtk.Window()
    win.set_app_paintable(True)
    visual = win.get_screen().get_rgba_visual()
    if visual:
        win.set_visual(visual)
    GtkLayerShell.init_for_window(win)
    GtkLayerShell.set_namespace(win, "pip-mirror")
    GtkLayerShell.set_layer(win, GtkLayerShell.Layer.TOP)
    corner = settings["corner"]
    vertical = GtkLayerShell.Edge.TOP if corner.startswith("top") else GtkLayerShell.Edge.BOTTOM
    side = GtkLayerShell.Edge.LEFT if corner.endswith("left") else GtkLayerShell.Edge.RIGHT
    for edge in (vertical, side):
        GtkLayerShell.set_anchor(win, edge, True)
        GtkLayerShell.set_margin(win, edge, MARGIN)
    GtkLayerShell.set_exclusive_zone(win, 0)       # 0, not -1: stays clear of the bar
    GtkLayerShell.set_keyboard_mode(win, GtkLayerShell.KeyboardMode.NONE)
    if mon:
        display = Gdk.Display.get_default()
        for i in range(display.get_n_monitors()):
            geo = display.get_monitor(i).get_geometry()
            if (geo.x, geo.y) == (mon["x"], mon["y"]):
                GtkLayerShell.set_monitor(win, display.get_monitor(i))
    area = Gtk.DrawingArea()
    area.set_size_request(*size)
    win.add(area)
    alpha = int(settings["opacity"]) / 100
    latest = {"pixbuf": None}

    def draw(_w, cr):
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        pb = latest["pixbuf"]
        if pb:
            Gdk.cairo_set_source_pixbuf(cr, pb, 0, 0)
            cr.paint_with_alpha(alpha)
        return True

    def frames():
        period, misses = 1 / int(settings["window_fps" if source["mode"] == "window" else "fps"]), 0
        argv = grim_argv(source)
        while True:
            t = time.monotonic()
            res = subprocess.run(argv, capture_output=True)
            try:
                w, h, rgb = parse_ppm(res.stdout)
                pb = GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(rgb), GdkPixbuf.Colorspace.RGB, False, 8,
                                                     w, h, w * 3)
                # Scaled here, off the GTK thread: drawing is then a plain copy.
                pb = pb.scale_simple(size[0], size[1], GdkPixbuf.InterpType.BILINEAR)
                misses = 0
            except (ValueError, IndexError, GLib.Error):
                misses += 1
                if misses >= 5:
                    GLib.idle_add(Gtk.main_quit)
                    return
                pb = None
            if pb:
                def show(p=pb):
                    latest["pixbuf"] = p
                    area.queue_draw()
                    return False
                GLib.idle_add(show)
            time.sleep(max(0.0, period - (time.monotonic() - t)))

    area.connect("draw", draw)
    win.connect("realize", lambda w: w.input_shape_combine_region(cairo.Region()))     # click-through
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    threading.Thread(target=frames, daemon=True).start()
    try:                                           # pip.py close: quit the loop, then supervise() cleans up
        gi.require_version("GLibUnix", "2.0")
        from gi.repository import GLibUnix
        GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda: (Gtk.main_quit(), False)[1])
    except (ImportError, ValueError):              # an older GLib
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda: (Gtk.main_quit(), False)[1])
    Gtk.main()


# -- main -----------------------------------------------------------------------------------
def main(argv):
    cmd, rest = (argv[0], argv[1:]) if argv else ("", [])
    as_json = "--json" in rest
    if cmd in ("window", "region"):
        start(cmd, rest)
    elif cmd == "toggle":
        if not close():
            start("window", rest)
    elif cmd == "close":
        close()
    elif cmd == "run" and rest:
        supervise(json.loads(rest[0]))
    elif cmd == "status":
        info = running()
        if as_json:
            print(json.dumps(info))
        else:
            print(f"mirroring {info['mode']}: {info['title']}" if info else "no mirror")
    elif cmd == "get":
        values = read_settings()
        print(json.dumps(values) if as_json else "\n".join(f"{k}={v}" for k, v in values.items()))
    elif cmd == "set" and len(rest) == 2:
        try:
            write_setting(*rest)
        except ValueError as exc:
            sys.exit(str(exc))
        if rest[0] == "opacity":
            hypr_eval('require("lua.pip").apply()')
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
