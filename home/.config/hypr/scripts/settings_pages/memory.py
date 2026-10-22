"""Settings page: desktop memory -- what went past on this computer, kept
with its time so "remember ..." in the search bar can find it again
(desktop-memory.py, whose docstring explains the sources and the store).

    DESKTOP MEMORY     on / off, how much is kept and how big, the last
                       collect; Collect now; a box to ask it something
    SOURCES            window titles, copies, notifications, live captions,
                       screenshots + OCR: one switch each (privacy.conf
                       memory_<source>, the same switches as Settings >
                       Privacy), how many memories each has, since when
    HOW LONG           memories kept for, screenshots kept for, a screenshot
                       every ... minutes
    FORGET             a day (the last eight as chips), an app (and none of
                       it from then on; "Remember again" undoes that), one
                       source's memories, or everything

The switches and times go through privacy_settings.py memory ...; the
forgetting through desktop-memory.py forget / wipe. Everything that throws
something away asks first, inline, like the Privacy page.
"""
import datetime
import os
import subprocess

from gi.repository import GLib, Gtk  # noqa: F401

from .common import *  # noqa: F401,F403  (the shared helpers and paths)

PAGE = {"id": "memory", "title": "Desktop memory", "icon": "", "group": "Safety", "order": 22,
        "keywords": ["memoria", "recuerda", "remember", "recall", "what did I see", "history", "historial",
                     "screenshots ocr", "notifications history", "captions log", "forget day", "forget app",
                     "wipe memory", "olvidar", "timeline"]}

MEMORY = os.path.join(HYPR, "desktop-memory.py")
PRIVACY = os.path.join(HYPR, "privacy_settings.py")
UNIT = "desktop-memory.service"
SOURCES = [
    ("activity", "", "Window titles", "which window had the focus and for how long (the activity "
                                           "history on Settings > Privacy must be on too)"),
    ("clipboard", "", "Copies", "new text you copy (the clipboard history must be on); passwords, "
                                     "card numbers, keys and tokens are never kept"),
    ("notifications", "", "Notifications", "what mako showed (low-urgency toasts left out); "
                                                "one-time codes are never kept"),
    ("captions", "", "Live captions", "the text of what live captions heard (SUPER+SHIFT+V), only "
                                           "while this is on. Off as shipped"),
    ("screen", "", "Screenshots + text", "every few minutes, the text on each screen (OCR) and a "
                                              "small picture; never while locked, in a game, on battery, or "
                                              "of a screen showing a password manager or a private window. "
                                              "Off as shipped"),
]
KEEP = [("7", "7 days"), ("30", "30 days"), ("90", "90 days"), ("365", "1 year")]
SCREEN_KEEP = [("1", "1 day"), ("7", "7 days"), ("30", "30 days")]
EVERY = [("5", "5 min"), ("15", "15 min"), ("30", "30 min"), ("60", "1 hour")]
NOUN = {"activity": "window titles", "clipboard": "copies", "notifications": "notifications",
        "captions": "captions", "screen": "screenshots"}


def size_text(n):
    if not n:
        return "0 B"
    if n < 1024 * 1024:
        return f"{max(1, n // 1024)} KiB"
    return f"{n / 1024 / 1024:.1f} MiB"


def when_text(epoch, now=None):
    if not epoch:
        return "never"
    now = now or datetime.datetime.now()
    then = datetime.datetime.fromtimestamp(epoch)
    days = (now.date() - then.date()).days
    if days == 0:
        return f"today {then:%H:%M}"
    if days == 1:
        return f"yesterday {then:%H:%M}"
    return f"{then:%a %d %b}"


def last_days(now=None, n=8):
    """[(iso date, label)] for today and the n-1 days before it."""
    now = now or datetime.datetime.now()
    out = []
    for i in range(n):
        d = now.date() - datetime.timedelta(days=i)
        out.append((d.isoformat(), "Today" if i == 0 else "Yesterday" if i == 1 else f"{d:%a %d}"))
    return out


def chips_line(chips):
    chips.widget.set_min_children_per_line(4)
    chips.widget.set_halign(Gtk.Align.START)
    chips.widget.set_margin_start(52)
    return chips.widget


class Page:
    def __init__(self):
        self.widget = page_box()
        w = self.widget
        self.updating = False
        self.data = None

        w.pack_start(heading("DESKTOP MEMORY"), False, False, 0)
        self.master = self.switch(lambda on: self.privacy("memory", "on" if on else "off"))
        grid, self.master_sub = row("", "Remember what goes past", "", self.master)
        w.pack_start(grid, False, False, 0)
        ask = Gtk.Box(spacing=8)
        ask.set_halign(Gtk.Align.END)
        self.question = Gtk.Entry()
        self.question.set_placeholder_text("what link did someone send on Tuesday?")
        self.question.set_width_chars(40)
        self.question.connect("activate", lambda _e: self.ask())
        ask.pack_start(self.question, False, False, 0)
        ask.pack_start(link("Remember", self.ask), False, False, 0)
        ask.pack_start(link("Collect now", self.collect), False, False, 0)
        w.pack_start(ask, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("SOURCES"), False, False, 0)
        self.src_switch, self.src_sub, self.src_rows = {}, {}, {}
        for key, icon, title, about in SOURCES:
            sw = self.switch(lambda on, k=key: self.privacy("memory", k, "on" if on else "off"))
            grid, sub = row(icon, title, about, sw)
            self.src_switch[key], self.src_sub[key], self.src_rows[key] = sw, sub, grid
            w.pack_start(grid, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("HOW LONG"), False, False, 0)
        self.keep = Chips(lambda k: self.shorter("keep", k))
        grid, self.keep_sub = row("", "Keep memories for", "")
        w.pack_start(grid, False, False, 0)
        w.pack_start(chips_line(self.keep), False, False, 0)
        self.screen_keep = Chips(lambda k: self.shorter("screen-keep", k))
        grid, self.screen_keep_sub = row("", "Keep screenshots' text and pictures for", "")
        w.pack_start(grid, False, False, 0)
        w.pack_start(chips_line(self.screen_keep), False, False, 0)
        self.every = Chips(lambda k: self.privacy("memory", "every", k))
        grid, self.every_sub = row("", "A screenshot every", "")
        w.pack_start(grid, False, False, 0)
        w.pack_start(chips_line(self.every), False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("FORGET"), False, False, 0)
        self.days = Chips(self.day_picked)
        grid, _ = row("", "Forget a day", "everything from that day goes, and it is not taken in again "
                      "from the activity history")
        w.pack_start(grid, False, False, 0)
        w.pack_start(chips_line(self.days), False, False, 0)
        grid, _ = row("", "Forget an app", "its memories go, and nothing of it is kept from then on")
        w.pack_start(grid, False, False, 0)
        pick = Gtk.Box(spacing=8)
        pick.set_halign(Gtk.Align.END)
        self.app_entry = Gtk.ComboBoxText.new_with_entry()
        self.app_entry.get_child().set_placeholder_text("window class, e.g. org.telegram.desktop")
        self.app_entry.get_child().set_width_chars(34)
        pick.pack_start(self.app_entry, False, False, 0)
        pick.pack_start(link("Forget it…", self.app_picked), False, False, 0)
        w.pack_start(pick, False, False, 0)
        self.forgotten = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        w.pack_start(self.forgotten, False, False, 0)
        self.confirm_box = Gtk.Box(spacing=6)
        self.confirm_box.set_halign(Gtk.Align.END)
        w.pack_start(self.confirm_box, False, False, 0)
        self.forget_links()

        self.msg = dp.label("", "ctl-sub")
        self.msg.set_line_wrap(True)
        w.pack_start(self.msg, False, False, 0)

    # -- building blocks ----------------------------------------------------------
    def switch(self, on_change):
        sw = Gtk.Switch()
        sw.connect("state-set", lambda _s, state: self.switched(on_change, state))
        return sw

    def switched(self, on_change, state):
        if not self.updating:
            on_change(state)
        return True             # the switch moves when refresh() says the setting did

    def confirm(self, question, yes, argv):
        box = self.confirm_box
        clear(box)
        box.pack_start(dp.label(question, "ctl-sub"), False, False, 0)
        box.pack_start(link(yes, lambda: (self.forget_links(), self.run(*argv))), False, False, 0)
        box.pack_start(link("Cancel", self.forget_links), False, False, 0)
        box.show_all()

    def forget_links(self):
        box = self.confirm_box
        clear(box)
        box.pack_start(dp.label("Forget:", "ctl-sub"), False, False, 0)
        for key, _icon, title, _about in SOURCES:
            box.pack_start(link(title, lambda k=key, t=title: self.confirm(
                f"Forget every memory from {t.lower()}?", "Yes, forget them",
                (MEMORY, "forget", "source", k))), False, False, 0)
        box.pack_start(link("Everything…", lambda: self.confirm(
            "Wipe the whole desktop memory, screenshots and captions included?", "Yes, wipe it",
            (MEMORY, "wipe"))), False, False, 0)
        box.show_all()

    # -- doing things -------------------------------------------------------------------
    def run(self, *argv):
        def work():
            try:
                res = subprocess.run(argv, capture_output=True, text=True, timeout=120)
                return (res.stdout if res.returncode == 0 else res.stderr or res.stdout).strip()
            except (OSError, subprocess.SubprocessError) as exc:
                return str(exc)
        self.msg.set_text("")
        background(work, lambda out: (self.msg.set_text(out.splitlines()[-1] if out else ""), self.refresh()))

    def privacy(self, *args):
        self.run(PRIVACY, *args)

    def shorter(self, what, key):
        """A shorter time deletes the older memories at once: asks first."""
        s = self.data or {}
        now = s.get("keep_days" if what == "keep" else "screen_keep_days")
        if now is None or int(key) >= now:
            self.privacy("memory", what, key)
            return
        noun = "memories" if what == "keep" else "screenshots"
        self.confirm(f"Delete the {noun} older than {key} days now?", "Yes", (PRIVACY, "memory", what, key))

    def day_picked(self, day):
        label = dict(last_days()).get(day, day)
        self.confirm(f"Forget everything from {label.lower() if label in ('Today', 'Yesterday') else label}?",
                     "Yes, forget it", (MEMORY, "forget", "day", day))

    def app_picked(self):
        cls = self.app_entry.get_child().get_text().strip()
        if cls:
            self.app_entry.get_child().set_text("")
            self.confirm(f"Forget {cls} and keep nothing of it from now on?", "Yes, forget it",
                         (MEMORY, "forget", "app", cls))

    def ask(self):
        text = self.question.get_text().strip()
        if text:
            spawn(MEMORY, "recall", "--notify", text)
            self.msg.set_text("asked: the answer comes as a notification")

    def collect(self):
        spawn("systemctl", "--user", "start", "--no-block", UNIT)
        self.msg.set_text("collecting…")
        GLib.timeout_add_seconds(4, lambda: (self.refresh(), False)[1])

    def refresh(self):
        background(lambda: (run_json(MEMORY, "status", "--json", timeout=20),
                            run_json(MEMORY, "apps", "--json", timeout=20)), self.show)

    # -- drawing ---------------------------------------------------------------------------
    def show(self, result):
        data, apps = result
        if not data:
            self.msg.set_text("desktop-memory.py did not answer (run it in a terminal to see why)")
            return
        self.data = data
        self.updating = True
        try:
            on = data["on"]
            self.master.set_active(on)
            self.master.set_state(on)
            total = sum(s["count"] for s in data["sources"].values())
            self.master_sub.set_text(
                (f"{total} memories, {size_text(data.get('bytes'))} on this computer  ·  last collect "
                 f"{when_text(data.get('collected'))}  ·  type \"remember …\" or \"recuerda …\" in the search "
                 "bar  ·  answered by a local model, nothing leaves the computer") if on else
                "off: nothing new is kept" + (f"  ·  {total} memories from before stay until forgotten or "
                                              "past their days" if total else ""))
            for key, src in data["sources"].items():
                if key not in self.src_switch:
                    continue
                self.src_switch[key].set_active(src["switch"])
                self.src_switch[key].set_state(src["switch"])
                self.src_rows[key].set_sensitive(on)
                about = next(a for k, _i, _t, a in SOURCES if k == key)
                count = (f"{src['count']} {NOUN[key]} since {when_text(src['since'])}" if src["count"]
                         else "nothing kept yet")
                if key == "screen" and src["count"]:
                    count += f" ({size_text(data.get('thumbs_bytes'))} of pictures)"
                self.src_sub[key].set_text(f"{count}  ·  {about}")
            self.keep.set(KEEP, str(data["keep_days"]))
            self.keep_sub.set_text(f"{data['keep_days']} days; older memories are deleted by themselves")
            self.screen_keep.set(SCREEN_KEEP, str(data["screen_keep_days"]))
            self.screen_keep_sub.set_text(f"{data['screen_keep_days']} days (the rest of the memory keeps "
                                          f"its {data['keep_days']})")
            self.every.set(EVERY, str(data["screen_minutes"]))
            self.every_sub.set_text(f"every {data['screen_minutes']} minutes while Screenshots is on; the same "
                                    "text as last time is not kept twice")
            self.days.set(last_days(), None)
            clear(self.forgotten)
            for cls in data.get("exclude") or []:
                grid, _ = row("", cls, "forgotten: nothing of it is kept",
                              link("Remember again", lambda c=cls: self.privacy("memory", "include", c)))
                self.forgotten.pack_start(grid, False, False, 0)
            self.app_entry.remove_all()
            for a in apps or []:
                if a["app"] not in (data.get("exclude") or []):
                    self.app_entry.append_text(a["app"])
        finally:
            self.updating = False
        self.widget.show_all()
