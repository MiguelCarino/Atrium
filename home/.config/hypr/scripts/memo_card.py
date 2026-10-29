#!/usr/bin/env python3
"""The voice memo's card: while memo.py records, a small card under the bar
-- a red dot and the time, the sound as moving bars, a Stop button, and
(Settings > Voice, "Words while recording") what is being said, as Whisper
hears it. Only for show: the memo's own text is still written by memo.py
once it stops, from the whole recording.

It stays until the memo ends -- no click-catcher, no keyboard: a click
anywhere else goes to what is under it and the card stays. It watches
memo.py's pid file and closes itself when the recorder is gone (Stop here,
SUPER+CTRL+N, the capture pill or the panel).

    memo_card.py        started by memo.py start; one at a time (a pid file)

The bars: its own pw-record of the same microphone (MEMO_SOURCE), 16 kHz
mono, a loudness a 50 ms block. The words: the captions' cutter
(voice.Captions) on the same sound, each phrase sent to the voice daemon
(voice.py's socket, the model already on the card or loaded for it) as a
.raw file in tmpfs, deleted after. In gamemode, or when the engine is not
there, the words line just stays empty.
"""
import collections
import importlib.util
import math
import os
import queue
import signal
import subprocess
import sys
import threading
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.expanduser("~/.config/waybar/scripts"))
import panelui  # noqa: E402


def _load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), os.path.join(HERE, f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


memo = _load("memo")
voice = _load("voice")

PID_FILE = os.path.join(memo.RUNTIME, "memo-card.pid")
BLOCK = voice.BYTES_PER_S // 20      # 50 ms
BARS = 46
WIDTH, WAVE_H = 380, 44
TOP_MARGIN = 8                       # under the bar (the layer sits below its strip)
FULL_RMS = 6000                      # this loud fills a bar


def level(block):
    """0..1 for a block of s16 sound: its RMS on a soft (square-root) scale,
    so quiet speech still moves the bars."""
    return min(1.0, math.sqrt(voice.rms(block) / FULL_RMS))


class Card:
    def __init__(self):
        self.settings = voice.read_settings()
        self.levels = collections.deque([0.0] * BARS, maxlen=BARS)
        self.lines = []
        self.phrases = queue.Queue()
        self.rec = None
        self.started = (memo.read_pid() or (0, "", time.time()))[2]

        panelui.load_css()
        win = self.win = Gtk.Window()
        win.set_name("panel-window")
        win.set_app_paintable(True)
        visual = win.get_screen().get_rgba_visual()
        if visual:
            win.set_visual(visual)
        GtkLayerShell.init_for_window(win)
        GtkLayerShell.set_namespace(win, "waybar-memo")
        GtkLayerShell.set_layer(win, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_anchor(win, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_margin(win, GtkLayerShell.Edge.TOP, TOP_MARGIN)
        GtkLayerShell.set_keyboard_mode(win, GtkLayerShell.KeyboardMode.NONE)
        # The primary screen, where the bar (and the capture pill) is.
        origin = panelui.output_origin(panelui.fallback_output() or "")
        display = Gdk.Display.get_default()
        for i in range(display.get_n_monitors()):
            geo = display.get_monitor(i).get_geometry()
            if origin and (geo.x, geo.y) == origin:
                GtkLayerShell.set_monitor(win, display.get_monitor(i))

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        card.set_name("panel")
        win.add(card)

        head = Gtk.Box(spacing=8)
        dot = Gtk.Label()
        dot.set_markup("<span foreground='#ff453a'>●</span>")
        head.pack_start(dot, False, False, 0)
        title = Gtk.Label(label="Voice memo")
        title.get_style_context().add_class("ctl-title")
        head.pack_start(title, False, False, 0)
        self.clock = Gtk.Label(label="0:00")
        self.clock.get_style_context().add_class("ctl-value")
        head.pack_start(self.clock, False, False, 0)
        stop = Gtk.Button(label="Stop")
        stop.get_style_context().add_class("ctl-link")
        stop.set_can_focus(False)
        stop.connect("clicked", self.on_stop)
        head.pack_end(stop, False, False, 0)
        card.pack_start(head, False, False, 0)

        self.wave = Gtk.DrawingArea()
        self.wave.set_size_request(WIDTH, WAVE_H)
        self.wave.connect("draw", self.on_draw)
        card.pack_start(self.wave, False, False, 0)

        self.words = Gtk.Label()
        self.words.get_style_context().add_class("ctl-sub")
        self.words.set_line_wrap(True)
        self.words.set_max_width_chars(48)
        self.words.set_size_request(WIDTH, -1)
        self.words.set_xalign(0.0)
        self.words.set_no_show_all(True)
        card.pack_start(self.words, False, False, 0)

        self.dot, self.blink = dot, True
        win.show_all()
        if self.settings.get("memo_text") == "on":
            self.words.set_text("Listening…")
            self.words.show()
            threading.Thread(target=self.transcriber, daemon=True).start()
        threading.Thread(target=self.listen, daemon=True).start()
        GLib.timeout_add(50, self.tick)
        GLib.timeout_add(500, self.watch)

    # sound -----------------------------------------------------------------------
    def listen(self):
        argv = ["pw-record", "--rate", str(voice.RATE), "--channels", "1", "--format", "s16", "--raw",
                "-P", '{ media.name="Voice memo (card)" }', "-"]
        if memo.SOURCE == "@DEFAULT_MONITOR@":      # memo.py's test source: what the computer plays
            argv[-2] = '{ stream.capture.sink=true media.name="Voice memo (card)" }'
        elif memo.SOURCE != "default":
            argv[1:1] = ["--target", memo.SOURCE]
        try:
            self.rec = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except OSError:
            return
        cut = voice.Captions(step=10 ** 9, pause=voice.LIVE_PAUSE_S, max_s=12.0)
        carry = b""
        words = self.settings.get("memo_text") == "on"
        while True:
            data = self.rec.stdout.read1(BLOCK * 2)
            if not data:
                break
            data = carry + data
            whole = len(data) - len(data) % BLOCK
            for i in range(0, whole, BLOCK):
                self.levels.append(level(data[i:i + BLOCK]))
            carry = data[whole:]
            if words:
                for _kind, pcm in cut.feed(data[:whole]):
                    self.phrases.put(pcm)

    def transcriber(self):
        os.makedirs(voice.WORK_DIR, mode=0o700, exist_ok=True)
        path = os.path.join(voice.WORK_DIR, f"memo-card-{os.getpid()}.raw")
        try:
            while True:
                pcm = self.phrases.get()
                if pcm is None:
                    return
                with open(path, "wb") as handle:
                    handle.write(pcm)
                answer = voice.request({"cmd": "transcribe", "path": path}, timeout=60)
                text = (answer or {}).get("text", "").strip()
                if answer.get("error") and not self.lines:
                    GLib.idle_add(self.show_words, "")       # gamemode, no engine: no words
                    continue
                if text:
                    self.lines = (self.lines + [text])[-2:]
                    GLib.idle_add(self.show_words, " ".join(self.lines))
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def show_words(self, text):
        if text:
            self.words.set_text(text)
        else:
            self.words.hide()
        return False

    # drawing ---------------------------------------------------------------------
    def on_draw(self, widget, cr):
        w, h = widget.get_allocated_width(), widget.get_allocated_height()
        color = widget.get_style_context().get_color(widget.get_state_flags())
        step = w / BARS
        bar = max(2.0, step * 0.55)
        for i, value in enumerate(self.levels):
            height = max(3.0, value * (h - 4))
            x = i * step + (step - bar) / 2
            y = (h - height) / 2
            cr.set_source_rgba(color.red, color.green, color.blue, 0.35 + 0.65 * (i / BARS))
            radius = bar / 2
            cr.new_sub_path()
            cr.arc(x + radius, y + radius, radius, math.pi, 1.5 * math.pi)
            cr.arc(x + bar - radius, y + radius, radius, 1.5 * math.pi, 2 * math.pi)
            cr.arc(x + bar - radius, y + height - radius, radius, 0, 0.5 * math.pi)
            cr.arc(x + radius, y + height - radius, radius, 0.5 * math.pi, math.pi)
            cr.close_path()
            cr.fill()
        return False

    def tick(self):
        self.wave.queue_draw()
        self.clock.set_text(memo.clock(time.time() - self.started))
        return True

    def watch(self):
        """Closes the card once the memo is over (stopped from anywhere)."""
        self.blink = not self.blink
        self.dot.set_opacity(1.0 if self.blink else 0.35)
        if memo.read_pid() is None:
            self.quit()
            return False
        return True

    def on_stop(self, _button):
        subprocess.Popen([sys.executable, os.path.join(HERE, "memo.py"), "stop"], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def quit(self, *_):
        if self.rec and self.rec.poll() is None:
            self.rec.terminate()
        self.phrases.put(None)
        try:
            if open(PID_FILE).read().strip() == str(os.getpid()):
                os.unlink(PID_FILE)
        except OSError:
            pass
        Gtk.main_quit()


def running():
    try:
        pid = int(open(PID_FILE).read().strip())
        with open(f"/proc/{pid}/cmdline", "rb") as handle:
            return b"memo_card.py" in handle.read()
    except (OSError, ValueError):
        return False


def main():
    if running() or memo.read_pid() is None:
        return 0
    with open(PID_FILE, "w") as handle:
        handle.write(str(os.getpid()))
    card = Card()
    for sig in (signal.SIGTERM, signal.SIGINT):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, lambda c=card: (c.quit(), False)[1])
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
