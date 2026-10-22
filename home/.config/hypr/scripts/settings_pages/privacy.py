"""Settings page: privacy -- what the desktop remembers about you and who may
read it (privacy_settings.py, which also explains where each setting lives).

    ACTIVITY HISTORY       activity-log.service on / off, how many days are
                           kept, the apps logged as "private", forget the last
                           hour / day / everything
    CLIPBOARD HISTORY      the cliphist@ recorders on / off, how many copies
                           are kept, clear it; what is never stored
    ASK YOUR DESKTOP       on / off, and which of files / clipboard / activity
                           the local model may read; the link to Folder access
                           (settings_pages/folders.py: which folders' files
                           any AI feature may read, asked first)
    SEARCH INDEX           search by meaning (desktop-index.py) on / off, which
                           folders it reads, how big it is, Update now, Delete
                           the index
    DESKTOP MEMORY         desktop-memory.py on / off and each of its sources
                           (window titles, copies, notifications, captions,
                           screenshots + OCR); the forgetting is on its own page
    RECENTLY USED FILES    GTK's list (file pickers, Files): on / off, how long,
                           clear it
    PRESENCE (WEBCAM)      presence.py on / off (OFF as shipped): may the camera
                           tell whether you are at the desk; its page has the rest
    IN USE RIGHT NOW       screen sharing, microphone, camera, location -- the
                           bar's own indicators, and what each one means
    YOUR LOCATION          what the weather and the emergency alerts are told,
                           with links to those pages

Everything that throws something away asks first, inline (no dialog
window): the link turns into "Really ...? [Yes] [Cancel]" in place.
"""
import datetime
import subprocess

from gi.repository import GLib, Gtk  # noqa: F401

from .common import *  # noqa: F401,F403  (the shared helpers and paths)

PAGE = {"id": "privacy", "title": "Privacy", "icon": "\uf505", "group": "Safety", "order": 20,
        "keywords": ["privacidad", "activity history", "clipboard history", "cliphist", "recent files",
                     "recently used", "ask your desktop", "local model", "camera", "microphone in use",
                     "screen sharing", "location", "forget history", "search index", "search by meaning",
                     "delete the index", "desktop memory", "screenshots ocr", "presence", "webcam"]}

PRIVACY = os.path.join(HYPR, "privacy_settings.py")
SETTINGS = os.path.join(HYPR, "settings.py")
CLIPBOARD = os.path.join(HYPR, "clipboard.py")
SUGGEST = os.path.join(HYPR, "suggest.py")
DESKTOP_INDEX = os.path.join(HYPR, "desktop-index.py")
INDEX_UNIT = "desktop-index.service"
INDEX_FOLDERS = ("~/Documents, ~/Downloads, ~/Desktop and the git repos in your projects folder (only the files git "
                 "keeps, so .gitignore is respected): text, Markdown, code, HTML, JSON, CSV and PDFs up "
                 "to 2 MB. Never hidden folders (~/.ssh, ~/.gnupg, keyrings, password stores, browser "
                 "profiles), node_modules, files named like *secret*, *credentials*, *password*, *.env, "
                 "id_rsa*, or anything holding a private key. The clipboard is not indexed.")
KEEP_CHOICES = [("1", "1 day"), ("7", "7 days"), ("30", "30 days"), ("90", "90 days")]
CLIP_CHOICES = [("50", "50"), ("100", "100"), ("500", "500"), ("1000", "1000")]
AGE_CHOICES = [("1", "1 day"), ("7", "7 days"), ("30", "30 days"), ("-1", "Never")]
SOURCE_ICON = {"files": "\uf15b", "clipboard": "\uf328", "activity": "\uf1da"}
SOURCE_TEXT = {
    "files": ("Files", "file names and dates under your home folder (no hidden folders), and the first "
                       "lines of the top PDFs and text files"),
    "clipboard": ("Clipboard", "the text entries of the clipboard history"),
    "activity": ("Activity", "the activity history above: which app and window had the focus, and when"),
}
# desktop-memory.py's sources (privacy.conf memory_<source>); its own page has the rest.
MEMORY_TEXT = {
    "activity": ("", "Window titles over time", "from the activity history above"),
    "clipboard": ("", "Copies", "new text copies; passwords, cards, keys and tokens never"),
    "notifications": ("", "Notifications", "what mako showed; one-time codes never"),
    "captions": ("", "Live captions", "the text of what live captions heard. Off as shipped"),
    "screen": ("", "Screenshots + text", "the text on screen every few minutes and a small picture; "
                                               "never of private windows, locked or in games. Off as shipped"),
}


def size_text(n):
    """Bytes as the page shows them: 980 B, 218 KiB, 56.5 MiB."""
    if n is None:
        return "?"
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n // 1024} KiB"
    return f"{n / 1024 / 1024:.1f} MiB"


def plural(n, word, many=None):
    return f"{n} {word if n == 1 else many or word + 's'}"


def chips_line(chips):
    """A Chips row on a line of its own under its ctl-row, lined up with the
    row's text (beside the row, the column is too narrow and they stack)."""
    chips.widget.set_min_children_per_line(4)
    chips.widget.set_halign(Gtk.Align.START)
    chips.widget.set_margin_start(52)
    return chips.widget


def since_text(epoch, now=None):
    """'since 02:05 today' / 'since yesterday 23:10' / 'since Mon 14 Oct'."""
    if not epoch:
        return "nothing logged yet"
    now = now or datetime.datetime.now()
    then = datetime.datetime.fromtimestamp(epoch)
    days = (now.date() - then.date()).days
    if days == 0:
        return f"since {then:%H:%M} today"
    if days == 1:
        return f"since yesterday {then:%H:%M}"
    return f"since {then:%a %d %b}"


def in_use_text(users, what):
    """The sub line for one live indicator: None = could not check."""
    if users is None:
        return f"could not check the {what}"
    if not users:
        return "not in use"
    return "in use by " + ", ".join(users[:4])


def show_switch(switch, on):
    """Show `on` on a switch. Both halves: state-set returns True (the
    switch moves when refresh() says the setting did), so a click leaves
    `active` (the knob) at the clicked position while `state` is the old
    one, and set_state() of an unchanged state does not move the knob back
    -- after a Cancel or a command that failed it would stay where it was
    clicked. set_active() first puts the knob where the setting is."""
    switch.set_active(on)
    switch.set_state(on)


def age_text(days):
    if days is None or days < 0:
        return "kept until you clear them"
    if days == 0:
        return "not kept at all"
    return f"older than {plural(days, 'day')} are dropped"


def presence_text(p):
    if not p.get("on"):
        return ("off: nothing opens the camera. On, it looks once or twice a second (in memory, nothing "
                "saved or sent) to lock when you leave and wake the screens when you are back")
    running = "running" if p.get("service") == "active" else f"the service is {p.get('service') or 'stopped'}"
    return (f"on, {running}  ·  frames are looked at in memory and dropped; the bar's camera icon says "
            "\"presence\" while the camera is open")


class Page:
    def __init__(self):
        self.widget = page_box()
        w = self.widget
        self.updating = False
        self.data = None

        # -- activity history ------------------------------------------------
        w.pack_start(heading("ACTIVITY HISTORY"), False, False, 0)
        self.act_switch = self.switch(lambda on: self.act("activity", "on" if on else "off"))
        grid, self.act_sub = row("\uf1da", "Remember which window had the focus", "", self.act_switch)
        w.pack_start(grid, False, False, 0)
        self.keep = Chips(self.keep_picked)
        grid, self.keep_sub = row("\uf017", "Keep it for", "")
        w.pack_start(grid, False, False, 0)
        w.pack_start(chips_line(self.keep), False, False, 0)
        grid, _ = row("\uf070", "Private apps", "KeePassXC and private / incognito browser windows are always "
                      "logged as \"private\": the time is kept, not the app or what was in it. Apps you add "
                      "here are logged the same way, and their past entries are made private too.")
        w.pack_start(grid, False, False, 0)
        self.private = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        w.pack_start(self.private, False, False, 0)
        add = Gtk.Box(spacing=8)
        add.set_halign(Gtk.Align.END)
        self.cls_entry = Gtk.ComboBoxText.new_with_entry()
        self.cls_entry.get_child().set_placeholder_text("window class, e.g. org.telegram.desktop")
        self.cls_entry.get_child().set_width_chars(34)
        self.cls_entry.get_child().connect("activate", lambda _e: self.add_private())
        add.pack_start(self.cls_entry, False, False, 0)
        add.pack_start(link("Make private", self.add_private), False, False, 0)
        w.pack_start(add, False, False, 0)
        self.act_confirm = Gtk.Box(spacing=6)
        self.act_confirm.set_halign(Gtk.Align.END)
        w.pack_start(self.act_confirm, False, False, 0)
        self.forget_links()
        w.pack_start(sep(), False, False, 0)

        # -- clipboard ---------------------------------------------------------
        w.pack_start(heading("CLIPBOARD HISTORY"), False, False, 0)
        self.clip_switch = self.switch(lambda on: self.act("clipboard", "on" if on else "off"))
        grid, self.clip_sub = row("\uf328", "Remember what you copy", "", self.clip_switch)
        w.pack_start(grid, False, False, 0)
        self.clip_max = Chips(self.clip_max_picked)
        grid, self.clip_max_sub = row("\uf0cb", "Copies kept", "")
        w.pack_start(grid, False, False, 0)
        w.pack_start(chips_line(self.clip_max), False, False, 0)
        grid, self.sensitive_sub = row("\uf084", "Passwords are never kept", "")
        w.pack_start(grid, False, False, 0)
        self.clip_confirm = Gtk.Box(spacing=6)
        self.clip_confirm.set_halign(Gtk.Align.END)
        w.pack_start(self.clip_confirm, False, False, 0)
        self.clip_links()
        # smart-clipboard.py: its own page has the switch and each kind
        grid, _ = row("", "Suggestions when you copy",
                      "The smart clipboard looks at each copy on this computer (fast rules, no model) to offer "
                      "an action; never at passwords, secrets or copies from private windows.")
        w.pack_start(grid, False, False, 0)
        w.pack_start(links_row(link("Open Smart clipboard", lambda: spawn(SETTINGS, "smartclip"))),
                     False, False, 0)
        # suggest.py (Live suggestions): this switch is its unit; its own page has each kind
        self.suggest_switch = self.switch(lambda on: self.suggest_set("on" if on else "off"))
        grid, self.suggest_sub = row("", "Live suggestions",
                                     "Looks at which window has the focus (and the git state of a terminal's or "
                                     "editor's folder), the lock and sleep, on this computer only, to offer a "
                                     "next step; never into private windows, and window titles are not kept.",
                                     self.suggest_switch)
        w.pack_start(grid, False, False, 0)
        w.pack_start(links_row(link("Open Live suggestions", lambda: spawn(SETTINGS, "suggestions"))),
                     False, False, 0)
        # focus-guard.py: noticing scattered switching (privacy.conf focus_watch; off as shipped)
        self.focus_switch = self.switch(lambda on: self.act("focus", "watch", "on" if on else "off"))
        grid, _ = row("", "Focus guard: notice scattered switching",
                      "Follows which window has the focus, on this computer only, to offer a focus block when "
                      "you hop between unrelated windows. Each window is reduced at once to its project or app; "
                      "titles are not kept and private windows are not looked into. Off as shipped.",
                      self.focus_switch)
        w.pack_start(grid, False, False, 0)
        w.pack_start(links_row(link("Open Focus", lambda: spawn(SETTINGS, "focus"))), False, False, 0)
        w.pack_start(sep(), False, False, 0)

        # -- ask your desktop ------------------------------------------------------
        w.pack_start(heading("ASK YOUR DESKTOP"), False, False, 0)
        self.ask_switch = self.switch(lambda on: self.act("ask", "on" if on else "off"))
        grid, self.ask_sub = row("\uf002", "Ask your desktop", "", self.ask_switch)
        w.pack_start(grid, False, False, 0)
        self.source_switches, self.source_rows = {}, {}
        for key, (title, sub) in SOURCE_TEXT.items():
            sw = self.switch(lambda on, k=key: self.act("ask", k, "on" if on else "off"))
            grid, _ = row(SOURCE_ICON[key], f"May read: {title}", sub, sw)
            self.source_switches[key], self.source_rows[key] = sw, grid
            w.pack_start(grid, False, False, 0)
        grid, _ = row("\uf07c", "Folder access for AI",
                      "Which folders the assistant, the LLM chat window, the local worker, Ask your desktop, background "
                      "tasks and the phone may read files in. A folder nobody opened yet is asked about first "
                      "(Deny / Allow once / Always allow); secret folders are never read.",
                      link("Open Folder access", lambda: spawn(SETTINGS, "folders")))
        w.pack_start(grid, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        # -- search index -------------------------------------------------------------
        w.pack_start(heading("SEARCH INDEX"), False, False, 0)
        self.index_switch = self.switch(lambda on: self.act("ask", "index", "on" if on else "off"))
        grid, self.index_sub = row("\uf002", "Search inside your documents by meaning", "", self.index_switch)
        self.index_row = grid
        w.pack_start(grid, False, False, 0)
        grid, _ = row("\uf07c", "Folders it reads", INDEX_FOLDERS)
        w.pack_start(grid, False, False, 0)
        grid, self.index_state = row("\uf1c0", "The index", "")
        w.pack_start(grid, False, False, 0)
        self.index_confirm = Gtk.Box(spacing=6)
        self.index_confirm.set_halign(Gtk.Align.END)
        w.pack_start(self.index_confirm, False, False, 0)
        self.index_links()
        w.pack_start(sep(), False, False, 0)

        # -- desktop memory (desktop-memory.py; Settings > Desktop memory has the rest) --
        w.pack_start(heading("DESKTOP MEMORY"), False, False, 0)
        self.mem_switch = self.switch(lambda on: self.act("memory", "on" if on else "off"))
        grid, self.mem_sub = row("", "Remember what goes past, with its time", "", self.mem_switch)
        w.pack_start(grid, False, False, 0)
        self.mem_switches, self.mem_rows = {}, {}
        for key, (icon, title, sub) in MEMORY_TEXT.items():
            sw = self.switch(lambda on, k=key: self.act("memory", k, "on" if on else "off"))
            grid, _ = row(icon, title, sub, sw)
            self.mem_switches[key], self.mem_rows[key] = sw, grid
            w.pack_start(grid, False, False, 0)
        w.pack_start(links_row(link("Open Desktop memory (forget a day, an app, wipe)",
                                    lambda: spawn(SETTINGS, "memory"))), False, False, 0)
        w.pack_start(sep(), False, False, 0)

        # -- recently used files ------------------------------------------------
        w.pack_start(heading("RECENTLY USED FILES"), False, False, 0)
        self.recent_switch = self.switch(self.recent_toggled)
        grid, self.recent_sub = row("\uf15b", "Remember recently used files", "", self.recent_switch)
        w.pack_start(grid, False, False, 0)
        self.recent_age = Chips(self.recent_age_picked)
        grid, self.recent_age_sub = row("\uf017", "Forget them after", "")
        w.pack_start(grid, False, False, 0)
        w.pack_start(chips_line(self.recent_age), False, False, 0)
        self.recent_confirm = Gtk.Box(spacing=6)
        self.recent_confirm.set_halign(Gtk.Align.END)
        w.pack_start(self.recent_confirm, False, False, 0)
        self.recent_links()
        w.pack_start(sep(), False, False, 0)

        # -- presence (presence.py: the webcam, off as shipped) --------------------
        w.pack_start(heading("PRESENCE (WEBCAM)"), False, False, 0)
        self.presence_switch = self.switch(lambda on: self.act("presence", "on" if on else "off"))
        grid, self.presence_sub = row("", "Let the webcam notice when you are at the desk", "",
                                      self.presence_switch)
        w.pack_start(grid, False, False, 0)
        w.pack_start(links_row(link("Open Presence", lambda: spawn(SETTINGS, "presence"))), False, False, 0)
        w.pack_start(sep(), False, False, 0)

        # -- live -------------------------------------------------------------
        w.pack_start(heading("IN USE RIGHT NOW"), False, False, 0)
        self.live = {}
        for key, icon, title in (("screen", "\uf108", "Screen sharing"), ("mic", "\uf130", "Microphone"),
                                 ("camera", "\uf030", "Camera"), ("location", "\uf3c5", "Location service")):
            grid, sub = row(icon, title, "checking…")
            self.live[key] = sub
            w.pack_start(grid, False, False, 0)
        note = dp.label("The top bar shows an icon while any of these is in use, and hides it when nothing "
                        "is: click the microphone or camera icon to go to the app using it. Sharing the "
                        "screen through the portal (calls, OBS) always asks which screen or window first. "
                        "Screenshots and the screen recorder (record.sh) are your own and do "
                        "not go through the portal: the recorder shows its own pill while it runs.",
                        "ctl-sub")
        note.set_line_wrap(True)
        note.set_max_width_chars(90)
        w.pack_start(note, False, False, 0)
        self.share_note = dp.label("", "ctl-sub")
        self.share_note.set_line_wrap(True)
        self.share_note.set_max_width_chars(90)
        w.pack_start(self.share_note, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        # -- location -------------------------------------------------------------
        w.pack_start(heading("YOUR LOCATION"), False, False, 0)
        grid, self.weather_sub = row("\uf6c4", "Weather", "", link("Open Region", lambda: spawn(SETTINGS, "region")))
        w.pack_start(grid, False, False, 0)
        grid, self.alerts_sub = row("\uf071", "Emergency alerts", "",
                                    link("Open Alerts", lambda: spawn(SETTINGS, "alerts")))
        w.pack_start(grid, False, False, 0)
        note = dp.label("Nothing here reads your position from the system's location service: the weather "
                        "and the alerts use the place you typed in. Apps that ask the location service "
                        "show up above while they do.", "ctl-sub")
        note.set_line_wrap(True)
        note.set_max_width_chars(90)
        w.pack_start(note, False, False, 0)

        self.msg = dp.label("", "ctl-sub")
        self.msg.set_line_wrap(True)
        w.pack_start(self.msg, False, False, 0)

    # -- building blocks ---------------------------------------------------------
    def switch(self, on_change):
        sw = Gtk.Switch()
        sw.connect("state-set", lambda _s, state: self.switched(on_change, state))
        return sw

    def switched(self, on_change, state):
        if not self.updating:
            on_change(state)
        return True             # the switch moves when refresh() says the setting did

    def confirm(self, box, question, yes, args, restore):
        """Swap the links in `box` for a question and Yes / Cancel."""
        clear(box)
        box.pack_start(dp.label(question, "ctl-sub"), False, False, 0)
        box.pack_start(link(yes, lambda: (restore(), self.act(*args) if args else self.index_clear())),
                            False, False, 0)
        box.pack_start(link("Cancel", restore), False, False, 0)
        box.show_all()

    def forget_links(self):
        box = self.act_confirm
        clear(box)
        for span, text, question in (
                ("hour", "Forget the last hour…", "Forget the last hour of activity?"),
                ("day", "Forget the last day…", "Forget the last 24 hours of activity?"),
                ("all", "Forget everything…", "Forget all of the activity history?")):
            box.pack_start(link(text, lambda s=span, q=question: self.confirm(
                box, q, "Yes, forget it", ("activity", "forget", s), self.forget_links)), False, False, 0)
        box.show_all()

    def clip_links(self):
        box = self.clip_confirm
        clear(box)
        box.pack_start(link("Open the history (SUPER+V)", lambda: spawn(CLIPBOARD)), False, False, 0)
        box.pack_start(link("Clear the history…", lambda: self.confirm(
            box, "Delete every copy in the clipboard history?", "Yes, clear it", ("clipboard", "clear"),
            self.clip_links)), False, False, 0)
        box.show_all()

    def recent_links(self):
        box = self.recent_confirm
        clear(box)
        box.pack_start(link("Clear the list…", lambda: self.confirm(
            box, "Empty the recently used files list? (The files themselves stay.)", "Yes, clear it",
            ("recent", "clear"), self.recent_links)), False, False, 0)
        box.show_all()

    def index_links(self):
        box = self.index_confirm
        clear(box)
        box.pack_start(link("Update now", self.index_update), False, False, 0)
        box.pack_start(link("Delete the index…", lambda: self.confirm(
            box, "Delete the search index? (Your files stay; it is built again at the next update "
            "while the switch is on.)", "Yes, delete it", None, self.index_links)), False, False, 0)
        box.show_all()

    def index_update(self):
        """The timer's own service, so it runs at nice 19 / idle I/O and
        goes on after this window closes."""
        self.msg.set_text("")
        spawn("systemctl", "--user", "start", "--no-block", INDEX_UNIT)
        GLib.timeout_add_seconds(2, lambda: (self.refresh(), False)[1])

    def index_clear(self):
        def work():
            subprocess.run(["systemctl", "--user", "stop", INDEX_UNIT], capture_output=True, timeout=30)
            try:
                res = subprocess.run([DESKTOP_INDEX, "clear"], capture_output=True, text=True, timeout=30)
                return "" if res.returncode == 0 else (res.stderr or res.stdout).strip()
            except (OSError, subprocess.SubprocessError) as exc:
                return str(exc)
        self.msg.set_text("")
        background(work, lambda err: (self.msg.set_text(err), self.refresh()))

    def recent_toggled(self, on):
        """Turning the list off EMPTIES it: every running GTK app clears
        recently-used.xbel when remember-recent-files goes false. So that
        asks first, like the other ways of throwing it away."""
        items = ((self.data or {}).get("recent") or {}).get("items") or 0
        if on or not items:
            self.act("recent", "on" if on else "off")
            return
        self.confirm(self.recent_confirm, f"Turning this off also empties the list ({plural(items, 'file')}). "
                     "Turn it off?", "Yes, turn it off", ("recent", "off"),
                     lambda: (self.recent_links(), self.refresh()))

    def recent_age_picked(self, key):
        """A shorter age deletes the entries older than it (GTK applies it
        to the file): asks first. Longer or "Never" just keeps more."""
        now = ((self.data or {}).get("recent") or {}).get("max_age")
        days = int(key)
        if days < 0 or (now is not None and 0 <= now <= days):
            self.act("recent", "age", key)
            return
        self.confirm(self.recent_confirm, f"Delete the entries older than {plural(days, 'day')} from the list?",
                     "Yes", ("recent", "age", key), self.recent_links)

    def keep_picked(self, key):
        """A shorter time deletes the older entries right away (the prune
        runs at once): asks first when there is something to delete.
        A longer time just keeps more."""
        a = (self.data or {}).get("activity") or {}
        days, now = int(key), a.get("keep_days")
        since = a.get("since")
        older = since is not None and since < datetime.datetime.now().timestamp() - days * 86400
        if now is None or days >= now or not older:
            self.act("activity", "keep", key)
            return
        self.confirm(self.act_confirm, f"Delete the activity older than {plural(days, 'day')} now?",
                     "Yes, delete it", ("activity", "keep", key), self.forget_links)

    def clip_max_picked(self, key):
        """Fewer copies than are saved deletes the oldest ones at the next
        copy: asks first. More just keeps more."""
        c = (self.data or {}).get("clipboard") or {}
        n, items = int(key), c.get("items") or 0
        if n >= (c.get("max_items") or 0) or items <= n:
            self.act("clipboard", "max", key)
            return
        self.confirm(self.clip_confirm, f"Keep only the newest {n}? The {items - n} older copies go "
                     "at the next copy.", "Yes", ("clipboard", "max", key), self.clip_links)

    def add_private(self):
        cls = self.cls_entry.get_child().get_text().strip()
        if cls:
            self.cls_entry.get_child().set_text("")
            self.act("activity", "exclude", cls)

    # -- doing things ----------------------------------------------------------------
    def act(self, *args):
        """Run privacy_settings.py <args> off the GTK thread, then redraw
        from what it reports; its complaint (if any) goes under the page."""
        def work():
            try:
                res = subprocess.run([PRIVACY, *args], capture_output=True, text=True, timeout=60)
                return "" if res.returncode == 0 else (res.stderr or res.stdout).strip()
            except (OSError, subprocess.SubprocessError) as exc:
                return str(exc)
        self.msg.set_text("")
        background(work, lambda err: (self.msg.set_text(err), self.refresh()))

    def suggest_set(self, value):
        """suggest.py set on|off (the unit), then the switch from what it says."""
        def work():
            try:
                res = subprocess.run([SUGGEST, "set", value], capture_output=True, text=True, timeout=30)
                return "" if res.returncode == 0 else (res.stderr or res.stdout).strip()
            except (OSError, subprocess.SubprocessError) as exc:
                return str(exc)
        background(work, lambda err: (self.msg.set_text(err), self.refresh()))

    def show_suggest(self, data):
        self.updating = True
        try:
            show_switch(self.suggest_switch, bool(data and data.get("on")))
        finally:
            self.updating = False

    def refresh(self):
        background(lambda: run_json(PRIVACY, "status", "--json", timeout=30), self.show)
        background(lambda: run_json(SUGGEST, "get", "--json"), self.show_suggest)

    # -- drawing -------------------------------------------------------------------
    def show(self, data):
        if not data:
            self.msg.set_text("privacy_settings.py did not answer (run it in a terminal to see why)")
            return
        self.data = data
        self.updating = True
        try:
            self.show_activity(data["activity"])
            self.show_clipboard(data["clipboard"])
            self.show_ask(data["ask"])
            self.show_index(data["ask"], data.get("index"))
            self.show_memory(data.get("memory"))
            self.show_recent(data["recent"])
            self.show_presence(data.get("presence"))
            show_switch(self.focus_switch, bool((data.get("focus") or {}).get("watch")))
            self.show_live(data["live"])
            self.show_location(data["location"])
        finally:
            self.updating = False
        self.widget.show_all()

    def show_activity(self, a):
        running = a["service"] == "active"
        show_switch(self.act_switch, running)
        if running:
            sub = (f"{plural(a.get('entries') or 0, 'entry', 'entries')} {since_text(a.get('since'))}, "
                   f"{size_text(a.get('bytes'))}  ·  stays on this computer; only Ask your desktop reads it")
        else:
            sub = ("off: nothing new is logged" + (f"  ·  {plural(a['entries'], 'entry', 'entries')} from before are "
                                                    "still kept until you forget them or they age out"
                                                    if a.get("entries") else ""))
        if running != a["enabled"]:
            sub += "  ·  " + ("not started at login" if running else "starts again at the next login")
        self.act_sub.set_text(sub)
        self.keep.set(KEEP_CHOICES, str(a["keep_days"]))
        self.keep_sub.set_text(f"{plural(a['keep_days'], 'day')}; older entries are deleted by themselves")
        clear(self.private)
        for cls in a["exclude"]:
            grid, _ = row("\uf070", cls, "logged as private", link("Remove", lambda c=cls: self.act(
                "activity", "include", c)))
            self.private.pack_start(grid, False, False, 0)
        self.cls_entry.remove_all()
        for cls in self.data.get("windows", []):
            if cls not in a["exclude"] and cls != "keepassxc":
                self.cls_entry.append_text(cls)

    def show_clipboard(self, c):
        show_switch(self.clip_switch, c["on"])
        if c["on"]:
            items = c.get("items")
            sub = (f"{plural(items, 'copy', 'copies') if items is not None else '?'} saved "
                   f"({size_text(c.get('db_bytes'))})  ·  SUPER+V picks one to paste again")
        else:
            sub = "off: new copies are not saved" + (
                f"  ·  {plural(c['items'], 'copy', 'copies')} from before are still there" if c.get("items") else "")
        if c["on"] != c["enabled"]:
            sub += "  ·  " + ("not started at login" if c["on"] else "starts again at the next login")
        self.clip_sub.set_text(sub)
        self.clip_max.set(CLIP_CHOICES, str(c["max_items"]))
        self.clip_max_sub.set_text(f"the newest {c['max_items']}; older ones go when you copy the next thing")
        if c.get("skips_sensitive"):
            self.sensitive_sub.set_text("KeePassXC (and any app that marks a copy as sensitive) is skipped: "
                                        "those copies never reach the history. Other password managers "
                                        "need to mark their copies the same way.")
        else:
            self.sensitive_sub.set_text(f"cliphist {c.get('version') or '(not found)'} does not skip copies "
                                        "marked sensitive; 0.6 or newer does (sudo dnf upgrade cliphist).")

    def show_ask(self, k):
        show_switch(self.ask_switch, k["on"])
        allowed = [SOURCE_TEXT[s][0].lower() for s, on in k["sources"].items() if on]
        if not k["on"]:
            sub = "off: \"ask …\" in the search bar answers that it is turned off"
        elif not allowed:
            sub = "on, but it may not read anything: turn on a source below"
        else:
            sub = ("type \"ask …\" in the search bar, e.g. \"ask what was I working on yesterday at 3pm\"  ·  "
                   "answered by a local model in LM Studio: nothing leaves the computer  ·  reads "
                   + ", ".join(allowed))
        self.ask_sub.set_text(sub)
        for key, sw in self.source_switches.items():
            show_switch(sw, k["sources"].get(key, True))
            self.source_rows[key].set_sensitive(k["on"])

    def show_index(self, k, idx):
        files_on = k["on"] and k["sources"].get("files", True)
        show_switch(self.index_switch, k.get("index", True))
        self.index_row.set_sensitive(files_on)
        if not files_on:
            sub = "off while Ask your desktop or its Files are off: nothing is indexed or searched"
        elif not k.get("index", True):
            sub = "off: nothing new is indexed and Ask does not search it"
        else:
            sub = ("Ask your desktop finds files by what they say, not only their names  ·  "
                   "updated every hour (not in game mode or on battery)  ·  stays on this computer")
        if idx and idx.get("exists") and not (files_on and k.get("index", True)):
            sub += "  ·  the index from before is kept until you delete it"
        self.index_sub.set_text(sub)
        if idx is None:
            self.index_state.set_text("desktop-index.py did not answer")
        elif not idx.get("exists"):
            self.index_state.set_text("not built yet" + ("  ·  building now…" if idx.get("running") else ""))
        else:
            when = (datetime.datetime.fromtimestamp(idx["updated"]).strftime("%a %d %b %H:%M")
                    if idx.get("updated") else "not finished yet")
            text = (f"{plural(idx.get('files') or 0, 'file')}, {plural(idx.get('chunks') or 0, 'piece')}, "
                    f"{size_text(idx.get('bytes'))}  ·  last update {when}  ·  "
                    + (f"meaning: {idx['model']}" if idx.get("model") else "keyword only (no embedding model)"))
            if idx.get("model") and idx.get("embedded", 0) < idx.get("chunks", 0) and not idx.get("running"):
                text += f" ({idx['embedded']} of {idx['chunks']} done)"
            if idx.get("running"):
                text += "  ·  updating now" + (f": {idx['progress']}" if idx.get("progress") else "")
            self.index_state.set_text(text)

    def show_memory(self, m):
        if not m:
            self.mem_sub.set_text("privacy_settings.py gave no desktop memory status")
            return
        show_switch(self.mem_switch, m["on"])
        store = m.get("store") or {}
        total = sum((s or {}).get("count", 0) for s in (store.get("sources") or {}).values())
        sub = (f"{plural(total, 'memory', 'memories')}, {size_text(store.get('bytes'))}, kept "
               f"{store.get('keep_days', '?')} days  ·  \"remember …\" in the search bar asks it  ·  "
               "stays on this computer") if m["on"] else (
            "off: nothing new is kept" + (f"  ·  {plural(total, 'memory', 'memories')} from before stay "
                                          "until forgotten" if total else ""))
        self.mem_sub.set_text(sub)
        for key, sw in self.mem_switches.items():
            show_switch(sw, m["sources"].get(key, False))
            self.mem_rows[key].set_sensitive(m["on"])

    def show_recent(self, r):
        on = r.get("on")
        show_switch(self.recent_switch, bool(on))
        self.recent_switch.set_sensitive(on is not None)
        if on is None:
            sub = "GSettings (org.gnome.desktop.privacy) did not answer"
        else:
            sub = (f"{plural(r.get('items') or 0, 'file')} in the list  ·  the Recent place in file pickers "
                   "and Files  ·  turning it off empties the list" if on else
                   "off: apps stop adding to the list") + (
                "" if on else (f"  ·  {plural(r['items'], 'file')} still listed" if r.get("items") else ""))
        self.recent_sub.set_text(sub)
        age = r.get("max_age")
        self.recent_age.set(AGE_CHOICES, "-1" if age is None or age < 0 else str(age))
        self.recent_age_sub.set_text(age_text(age) + "  ·  a shorter time deletes the older entries")

    def show_presence(self, p):
        p = p or {}
        show_switch(self.presence_switch, bool(p.get("on")))
        self.presence_sub.set_text(presence_text(p))

    def show_live(self, live):
        screen = live.get("screen")
        self.live["screen"].set_text("could not check (pw-dump)" if screen is None else
                                     "your screen is being shared right now" if screen else "not shared")
        self.live["mic"].set_text(in_use_text(live.get("mic"), "microphone"))
        self.live["camera"].set_text(in_use_text(live.get("camera"), "camera"))
        self.live["location"].set_text(in_use_text(live.get("location"), "location service"))
        dnd = live.get("share_dnd")
        self.share_note.set_text(
            "" if dnd is None else
            "While the screen is shared, Do Not Disturb turns itself on, so notifications do not show "
            "up on the call (Settings > Notifications)." if dnd else
            "Do Not Disturb does not turn itself on while the screen is shared: notifications can show "
            "up on a call (Settings > Notifications can change that).")

    def show_location(self, loc):
        place = loc.get("weather")
        if place is None:
            text = "could not read the weather's place"
        elif place == "":
            text = "wttr.in guesses it from your internet address"
        else:
            text = f"wttr.in is asked about \"{place}\" every half hour"
        self.weather_sub.set_text(text + "  ·  the forecast in the top bar")
        al = loc.get("alerts")
        if al:
            sent = al.get("sent_place")
            if sent is None:
                who = "could not check which sources are on"
            elif not sent:
                who = "no source is sent it: the feeds are downloaded whole and matched here"
            else:
                who = ("sent to " + " and ".join(sent) + " to ask about it; the other feeds are downloaded "
                       "whole and matched here")
            self.alerts_sub.set_text(f"your place: {al.get('lat')}, {al.get('lon')} ({al.get('country')})  ·  "
                                     + who)
        else:
            self.alerts_sub.set_text("emergency-alerts.py did not answer")
