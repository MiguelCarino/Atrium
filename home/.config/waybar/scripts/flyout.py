#!/usr/bin/env python3
"""Media preview panel — the thumbnail that hangs under the bar.

The preview is the video, playing. mpv's picture cannot be tapped: it renders to
its own Wayland surface and no client may read another's. So the panel opens the
same file a second time, muted, and keeps it in step with mpv's own clock over
IPC. Where that is impossible — a yt-dlp stream with no openable URL, a browser
tab, a music player, an mpv with no IPC socket — it falls back to a feed of
stills: frames pulled out of mpv, a thumbnailer seek, or cover art.

With more than one player up, a row of source buttons under the controls
switches which one the panel (and the bar pill) follows -- the same switch as
scrolling on the pill (player.py select / cycle).

Placement, styling and lifetime come from panelui.py / panel.py; state, control
and frame grabbing from player.py, so the bar pill and this panel can never
disagree about what is playing.

    flyout.py [x,y]   desktop position of the click that opened the panel
"""

import os
import sys
import threading
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Gst", "1.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gst, Gtk  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import panelui  # noqa: E402
import player  # noqa: E402

LIVE_FRAME = os.path.join(player.CACHE, "live.jpg")

PREVIEW_WIDTH = 320
PREVIEW_HEIGHT = 180        # fixed 16:9 box: the panel must not resize per frame

# --- staying in step with mpv ----------------------------------------------
# The panel is a second decode of the same file, so it only looks right if it
# tracks mpv closely. Two things push it behind: the seek that starts playback
# lands where mpv *was*, not where it will be by the time the first frame is up,
# and our own render adds a little on top. LEAD covers both, and the sync tick
# is fast enough that a pause or a seek in mpv shows up here almost at once.
SYNC_MS = 150
LEAD = 0.09                 # seconds to aim ahead of mpv's reported position
DRIFT_MAX = 0.30            # correct once we are further out than this
DRIFT_STRIKES = 2           # ... and only after two readings agree, so a single
                            # slow query cannot make the preview jump
PRIME_TOLERANCE = 0.15      # accuracy demanded of the very first seek: measured
                            # residual is ~0.12s, and re-seeking for that would
                            # be a flush nobody can see the benefit of
GST_PLAY_FLAG_VIDEO = 1 << 0

# --- still fallbacks (art, streams, files with no IPC socket) --------------
LIVE_MS = 110               # ~6 fps once mpv's ~65ms readback is paid for
PAUSED_MS = 500             # paused, but a seek still has to show up
SEEK_MS = 1000              # decoding a frame off disk, once a second, is
                            # already as much as ffmpegthumbnailer can take
STILL_MS = 3000             # cover art: nothing about it moves
META_MS = 500


def scaled(path, width, height):
    try:
        return GdkPixbuf.Pixbuf.new_from_file_at_scale(path, width, height, True)
    except GLib.Error:
        return None


def live_capable(state):
    """Only mpv can be asked for the frame it is showing right now. Anything
    else — a browser tab, a music player — gets a still."""
    return bool(state.get("socket")) and state.get("is_video")


def grab_live(state):
    """mpv writes the screenshot before it answers, so the file is whole by the
    time we get here — no half-written frames."""
    tmp = LIVE_FRAME + ".tmp.jpg"
    if not player.mpv_command(state["socket"], ["screenshot-to-file", tmp, "video"]):
        return False
    try:
        if os.path.getsize(tmp) == 0:
            return False
        os.replace(tmp, LIVE_FRAME)
    except OSError:
        return False
    return True


class VideoMirror:
    """The preview, actually playing.

    Audio is never decoded: a second PipeWire stream would light up the bar's
    own privacy indicator. Only local files qualify — a stream mpv resolved
    through yt-dlp has no URL GStreamer could open."""

    def __init__(self, on_failure):
        self.on_failure = on_failure
        self.widget = None
        self.pipeline = None
        self.path = None
        self.paused = None
        self.primed = False
        self.settling = False   # first frame is up; check the seek landed right
        self.target = 0.0
        self.strikes = 0

        sink = self.build_sink()
        if not sink:
            return
        self.pipeline = Gst.ElementFactory.make("playbin")
        if not self.pipeline:
            return
        self.pipeline.set_property("video-sink", sink)
        self.pipeline.set_property("flags", GST_PLAY_FLAG_VIDEO)
        # Scale down inside the pipeline: gtksink would otherwise hand cairo a
        # full-size frame to shrink on every single one, which costs more than
        # the decode. Height is left to videoscale so the aspect survives.
        try:
            scaler = Gst.parse_bin_from_description(
                "videoconvert ! videoscale ! "
                f"capsfilter caps=video/x-raw,width={PREVIEW_WIDTH}", True)
            self.pipeline.set_property("video-filter", scaler)
        except GLib.Error:
            pass                        # unscaled still plays, just costs more
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message::async-done", self.on_async_done)
        bus.connect("message::eos", self.on_eos)
        bus.connect("message::error", self.on_error)

    def build_sink(self):
        """gtksink, not gtkglsink: the GL sink cannot get a context inside a
        layer-shell surface here — it fails the pipeline with "Failed to
        initialize OpenGL with Gtk" even once the widget is mapped, and a
        preview this size does not need the GPU path anyway."""
        sink = Gst.ElementFactory.make("gtksink")
        if sink:
            self.widget = sink.props.widget
        return sink

    @property
    def usable(self):
        return self.pipeline is not None and self.widget is not None

    def follow(self, path, position, paused):
        """Open the file if it is new, otherwise just stay in step."""
        if not self.usable:
            return False
        if path != self.path:
            self.open(path, position, paused)
            return True
        self.sync(position, paused)
        return True

    def open(self, path, position, paused):
        self.pipeline.set_state(Gst.State.NULL)
        self.path = path
        self.primed = False
        self.settling = False
        self.strikes = 0
        self.target = position
        self.paused = paused
        self.pipeline.set_property("uri", Gst.filename_to_uri(path))
        # PAUSED first: the seek to mpv's position has to wait for preroll, or
        # the panel would show the opening frames before jumping.
        self.pipeline.set_state(Gst.State.PAUSED)

    def sync(self, position, paused):
        # Kept up to date even while prerolling: it is both where the first seek
        # lands and where EOS sends us back to.
        self.target = position
        if not self.primed:
            self.paused = paused
            return

        if paused != self.paused:
            self.paused = paused
            self.pipeline.set_state(Gst.State.PAUSED if paused else Gst.State.PLAYING)

        ok, ours = self.pipeline.query_position(Gst.Format.TIME)
        if not ok:
            return
        drift = position + LEAD - ours / Gst.SECOND

        if self.settling:
            # The opening seek aimed at where mpv would be once preroll ended.
            # Whatever it actually missed by is measurable now, so take it out
            # in one go rather than living with it for the rest of the file.
            if abs(drift) > PRIME_TOLERANCE:
                self.seek(position)
            self.settling = False
            return

        if abs(drift) > DRIFT_MAX:
            self.strikes += 1
            if self.strikes >= DRIFT_STRIKES:
                self.seek(position)
                self.strikes = 0
        else:
            self.strikes = 0

    def seek(self, position):
        self.pipeline.seek_simple(
            Gst.Format.TIME,
            Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE,
            max(0, int((position + LEAD) * Gst.SECOND)))

    def on_async_done(self, _bus, _message):
        if self.primed:
            return                      # our own seek finishing, not preroll
        self.primed = True
        self.settling = True
        self.seek(self.target)
        if not self.paused:
            self.pipeline.set_state(Gst.State.PLAYING)

    def on_eos(self, _bus, _message):
        # mpv looping, or us having run off the end: go back to where mpv is.
        self.seek(self.target)

    def on_error(self, _bus, message):
        error, _debug = message.parse_error()
        failed = self.path                  # close() forgets which file it was
        self.close()
        self.on_failure(failed, error.message)

    def close(self):
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
        self.path = None
        self.primed = False
        self.settling = False


class FrameFeed(threading.Thread):
    """Frames on a thread of their own. Asking mpv for the displayed frame costs
    ~65ms (GPU readback, then a JPEG), and ffmpegthumbnailer costs more than
    that — on the GTK loop it would show up as buttons that ignore clicks."""

    def __init__(self, window):
        super().__init__(daemon=True)
        self.window = window
        self.state = None
        self.interval = STILL_MS / 1000
        self.done = threading.Event()

    def run(self):
        while not self.done.is_set():
            started = time.monotonic()
            pixbuf = self.next_frame(self.state)
            if pixbuf is not None:
                GLib.idle_add(self.window.set_frame, pixbuf)
            # Pace from the start of the grab, so a slow frame costs time once
            # rather than twice.
            self.done.wait(max(0.02, self.interval - (time.monotonic() - started)))

    def next_frame(self, state):
        if not state:
            return None
        if live_capable(state):
            return scaled(LIVE_FRAME, PREVIEW_WIDTH, PREVIEW_HEIGHT) \
                if grab_live(state) else None
        if state["is_video"] and player.grab_frame(state, player.THUMB):
            return scaled(player.THUMB, PREVIEW_WIDTH, PREVIEW_HEIGHT)
        if player.cached_art(player.art_url(state), player.THUMB):
            return scaled(player.THUMB, PREVIEW_WIDTH, PREVIEW_HEIGHT)
        return None

    def stop(self):
        self.done.set()


class Flyout(panelui.Panel):
    def setup(self):
        self.state = None
        self.mirror = VideoMirror(self.on_mirror_failed)
        self.mirror_broken = set()      # files GStreamer could not open
        self.feed = FrameFeed(self)
        self.scrubbing = False

    # -- widgets ------------------------------------------------------------
    def build(self):
        self.image = Gtk.Image()
        self.image.set_name("preview")

        # Two ways to fill the same box: the file playing (mirror), or a still
        # for everything that cannot be played twice.
        self.stack = Gtk.Stack()
        self.stack.set_size_request(PREVIEW_WIDTH, PREVIEW_HEIGHT)
        self.stack.add_named(self.image, "still")
        if self.mirror.usable:
            self.stack.add_named(self.mirror.widget, "video")
            # Visible from the start so the sink's widget is the one GTK maps:
            # a hidden stack child is never realized.
            self.stack.set_visible_child_name("video")
            self.mirror.widget.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
            self.mirror.widget.connect("button-press-event",
                                       lambda *_: self.control("toggle"))

        frame = Gtk.EventBox()          # a bare Gtk.Image cannot take clicks
        frame.set_name("preview-frame")
        frame.add(self.stack)
        frame.connect("button-press-event", lambda *_: self.control("toggle"))
        self.card.pack_start(frame, False, False, 0)

        self.title_label = Gtk.Label(label="")
        self.title_label.set_name("title")
        self.title_label.set_ellipsize(3)   # Pango.EllipsizeMode.END
        self.card.pack_start(self.title_label, False, False, 0)

        self.subtitle_label = Gtk.Label(label="")
        self.subtitle_label.set_name("subtitle")
        self.card.pack_start(self.subtitle_label, False, False, 0)

        self.seek = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 1, 1)
        self.seek.set_name("seek")
        self.seek.set_draw_value(False)
        # Press/release rather than value-changed: the position is written to
        # this widget several times a second, and seeking mpv on every one of
        # those would fight the user for the handle.
        self.seek.connect("button-press-event", self.on_scrub_start)
        self.seek.connect("button-release-event", self.on_scrub_end)
        self.card.pack_start(self.seek, False, False, 0)

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        controls.set_name("controls")
        controls.set_halign(Gtk.Align.CENTER)
        self.play = self.button(player.PAUSE_BTN, "toggle", "play")
        controls.pack_start(self.button(player.PREV_ICON, "prev"), False, False, 0)
        controls.pack_start(self.play, False, False, 0)
        controls.pack_start(self.button(player.NEXT_ICON, "next"), False, False, 0)
        self.card.pack_start(controls, False, False, 0)

        # One button per player, the followed one lit; hidden with only one.
        self.sources = Gtk.FlowBox()
        self.sources.set_selection_mode(Gtk.SelectionMode.NONE)
        self.sources.set_max_children_per_line(3)
        self.sources.set_halign(Gtk.Align.CENTER)
        self.sources.set_no_show_all(True)
        self.card.pack_start(self.sources, False, False, 0)
        self.source_keys = None

    def button(self, icon, action, name="control"):
        widget = Gtk.Button(label=icon)
        widget.set_name(name)
        widget.get_style_context().add_class("control")
        widget.connect("clicked", lambda *_: self.control(action))
        return widget

    def on_ready(self):
        self.tick_meta()
        GLib.timeout_add(META_MS, self.tick_meta)
        GLib.timeout_add(SYNC_MS, self.tick_sync)
        self.feed.start()

    # -- playback -----------------------------------------------------------
    def control(self, action):
        player.do_control(action)
        self.tick_meta()
        return True

    def on_scrub_start(self, *_):
        self.scrubbing = True
        return False

    def on_scrub_end(self, *_):
        self.scrubbing = False
        player.do_seek(self.seek.get_value())
        self.tick_meta()
        return False

    # -- polling ------------------------------------------------------------
    def tick_meta(self):
        """Titles and artwork. Slow on purpose — none of it changes per frame."""
        state = player.current()
        if not state:
            self.quit()
            return False
        self.state = state

        self.title_label.set_text(player.clean_title(state["title"]))
        parts = []
        if state["artist"]:
            parts.append(state["artist"])
        if state["duration"]:
            parts.append(f"{player.hms(state['position'])} / "
                         f"{player.hms(state['duration'])}")
        else:
            parts.append(player.hms(state["position"]))
        parts.append("paused" if state["paused"] else state["source"] or "playing")
        self.subtitle_label.set_text(" · ".join(parts))

        self.play.set_label(player.PLAY_ICON if state["paused"] else player.PAUSE_BTN)
        self.seek.set_visible(bool(state["duration"]))
        if state["duration"]:
            self.seek.set_range(0, state["duration"])

        self.show_sources(state)
        self.choose_source(state)
        return True

    def show_sources(self, state):
        players = state.get("players") or []
        keys = [(p["player"], p["player"] == state["player"], p["paused"]) for p in players]
        if keys == self.source_keys:
            return                      # nothing changed: no rebuild under the pointer
        self.source_keys = keys
        for child in self.sources.get_children():
            self.sources.remove(child)
        if len(players) < 2:
            self.sources.hide()
            return
        for p in players:
            icon = player.PLAYER_ICONS.get(p["source"], player.DEFAULT_ICON)
            title = player.ellipsize(p["title"] or p["source"], 18)
            button = Gtk.Button(label=f"{icon}  {title}")
            button.get_style_context().add_class("dev-pick")
            if p["player"] == state["player"]:
                button.get_style_context().add_class("active")
            button.set_tooltip_text(f"{p['source']}{' (paused)' if p['paused'] else ''}")
            button.connect("clicked", lambda _b, name=p["player"]: self.pick_source(name))
            self.sources.add(button)
        # Shown one by one: show_all() is a no-op on a no_show_all widget.
        for child in self.sources.get_children():
            child.show_all()
        self.sources.show()

    def pick_source(self, name):
        player.select(name)
        self.tick_meta()

    def tick_sync(self):
        """The fast loop: where mpv is, and where the seek bar sits. Cheap —
        one IPC round trip on a socket that is already open."""
        state = self.state
        if not state:
            return True

        position, paused = self.mpv_clock(state)
        if not self.scrubbing and state["duration"]:
            self.seek.set_value(min(position, state["duration"]))

        if self.mirror.path:
            self.mirror.sync(position, paused)
            if paused != state["paused"]:
                # Reflect it immediately rather than waiting for tick_meta:
                # a glyph that lags the click by half a second feels broken.
                state["paused"] = paused
                self.play.set_label(
                    player.PLAY_ICON if paused else player.PAUSE_BTN)
        return True

    def choose_source(self, state):
        """Play the file when we can, fall back to frames when we cannot."""
        path = state["path"] if live_capable(state) else ""
        playable = (path and path not in self.mirror_broken and
                    os.path.exists(path) and self.mirror.usable)

        if playable:
            self.stack.set_visible_child_name("video")
            position, paused = self.mpv_clock(state)
            if self.mirror.follow(path, position, paused):
                self.feed.state = None      # the thread idles while we play
                return

        self.mirror.close()
        self.stack.set_visible_child_name("still")
        self.feed.state = state
        self.feed.interval = self.cadence(state) / 1000

    @staticmethod
    def mpv_clock(state):
        """Straight from mpv rather than the shared state cache: a position up
        to a second old would read as drift and trigger a pointless seek."""
        if not state.get("socket"):
            return state["position"], state["paused"]
        data = player.mpv_get(state["socket"], ["time-pos", "pause"])
        if "time-pos" not in data:
            return state["position"], state["paused"]
        return data["time-pos"] or 0.0, bool(data.get("pause"))

    def cadence(self, state):
        """Frames only need to arrive as fast as they change."""
        if live_capable(state):
            return PAUSED_MS if state["paused"] else LIVE_MS
        if state["is_video"] and not state["paused"] and state["path"]:
            return SEEK_MS
        return STILL_MS

    def set_frame(self, pixbuf):
        """Called from the frame thread by way of GLib.idle_add, so it runs on
        the GTK loop like every other widget touch here."""
        self.image.set_from_pixbuf(pixbuf)
        return False

    def on_mirror_failed(self, path, reason):
        """A file GStreamer cannot decode is not worth retrying every tick."""
        if path:
            self.mirror_broken.add(path)
        print(f"flyout.py: cannot play {path!r} ({reason}); falling back to frames",
              file=sys.stderr)

    def quit(self):
        self.feed.stop()
        self.mirror.close()
        super().quit()


def main():
    Gst.init(None)
    os.makedirs(player.CACHE, exist_ok=True)
    if not player.current():
        return          # nothing playing: there would be nothing to show
    panelui.run(Flyout)


if __name__ == "__main__":
    main()
