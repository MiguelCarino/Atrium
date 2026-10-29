"""Settings page: the notes inbox -- where quick notes (quicknote.py,
SUPER+SHIFT+N) and voice memos (memo.py, SUPER+CTRL+N) land.

The inbox is one markdown file, ~/Documents/Notes/inbox.md ($MEMO_INBOX
moves it, as it does for memo.py), one list item a note:

    - 2026-10-28 09:41  call the supplier about the PSU
    - 2026-10-28 09:45  [memo](~/Documents/Memos/2026-10-28_09-45-02.opus) what was said

A tab of Screenshots & recording, beside the other quick-capture tools
(the sidebar is kept to one screen of pages). The page lists them newest first: the text, when, and for a memo Play (the
sound in the default player) and Text (its .txt). Delete takes the line out
of the inbox -- it asks first, the button turns into "Delete?" for a few
seconds -- and leaves a memo's sound and text files where they are (the
memos folder link is there for those). Open the inbox opens the whole file
in the default editor; a hand edit there is what the page shows next time.
Nothing here is kept by the page: it reads the file on every refresh and
rewrites it (atomically, keeping every other line) only on a delete.
"""
from gi.repository import GLib, Gtk  # noqa: F401

from .common import *  # noqa: F401,F403  (the shared helpers and paths)

import os  # noqa: E402
import re  # noqa: E402

PAGE = {"id": "notes", "title": "Notes inbox", "icon": "", "group": "Apps", "order": 32,
        "parent": "capture", "tab": "Notes & memos",
        "keywords": ["notes", "notas", "quick note", "inbox", "voice memo", "memo", "memos", "recordings",
                     "transcript", "delete note", "jot"]}

INBOX = os.path.expanduser(os.environ.get("MEMO_INBOX", "~/Documents/Notes/inbox.md"))  # = memo.py / quicknote.py
MEMO_DIR = os.path.expanduser(os.environ.get("MEMO_DIR", "~/Documents/Memos"))
QUICKNOTE = os.path.join(HYPR, "quicknote.py")
SHOWN = 60                  # the newest this many; the rest are in the file
ITEM = re.compile(r"^- (\d{4}-\d{2}-\d{2} \d{2}:\d{2})\s+(.*)$")
MEMO = re.compile(r"\[memo\]\(([^)]+)\)\s*")


# -- pure helpers (tests/test_settings_desk.py) ----------------------------------------
def parse_inbox(text):
    """The inbox's notes, in file order: [{index (line number), raw (the
    line), when ("YYYY-MM-DD HH:MM"), text, memo (the sound's path, ~
    expanded, or None)}]. Lines that are not "- <date> <time>  ..." items
    (the heading, the intro, a hand-written line) are not notes."""
    out = []
    for n, line in enumerate(text.splitlines()):
        m = ITEM.match(line)
        if not m:
            continue
        body = m[2].strip()
        memo = MEMO.search(body)
        path = os.path.expanduser(memo[1]) if memo else None
        if memo:
            body = (body[:memo.start()] + body[memo.end():]).strip()
        out.append({"index": n, "raw": line, "when": m[1], "text": body, "memo": path})
    return out


def remove_note(text, index, raw):
    """The inbox text without line `index`, which must still be `raw` (the
    file may have changed since the page read it: then the first line equal
    to raw goes, and None when there is none -- nothing is removed)."""
    lines = text.splitlines(keepends=True)
    if 0 <= index < len(lines) and lines[index].rstrip("\r\n") == raw:
        del lines[index]
        return "".join(lines)
    for n, line in enumerate(lines):
        if line.rstrip("\r\n") == raw:
            del lines[n]
            return "".join(lines)
    return None


def note_sub(note, today=None):
    """'today 09:41', 'memo  ·  2026-10-27 18:02'."""
    day, hm = note["when"].split(" ")
    when = f"today {hm}" if today and day == today else note["when"]
    return f"voice memo  ·  {when}" if note["memo"] else when


def short(text, limit=160):
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def read_inbox(path=None):
    try:
        with open(path or INBOX, encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return None


def write_inbox(text, path=None):
    path = path or INBOX
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(tmp, path)


class Page:
    def __init__(self):
        self.widget = page_box()
        w = self.widget
        self.error = dp.label("", "ctl-sub")
        self.error.set_line_wrap(True)
        self.error.set_no_show_all(True)
        w.pack_start(self.error, False, False, 0)

        w.pack_start(heading("INBOX"), False, False, 0)
        self.summary_row, self.summary = row("", "Notes inbox", "checking…")
        w.pack_start(self.summary_row, False, False, 0)
        w.pack_start(links_row(link("New quick note", lambda: spawn(QUICKNOTE)),
                               link("Open the inbox", self.open_inbox),
                               link("Memos folder", lambda: spawn("xdg-open", MEMO_DIR))), False, False, 0)
        w.pack_start(sep(), False, False, 0)
        w.pack_start(heading("NOTES"), False, False, 0)
        self.rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        w.pack_start(self.rows, False, False, 0)
        more = dp.label("Quick notes: SUPER+SHIFT+N. Voice memos: SUPER+CTRL+N (Settings > Voice typing "
                        "writes them down). Delete takes the line out of the inbox; a memo's sound and "
                        "text files stay in the memos folder.", "ctl-sub")
        more.set_line_wrap(True)
        more.set_xalign(0)
        w.pack_start(details(more), False, False, 0)
        self.armed = None           # the line whose Delete was clicked once

    # -- actions ---------------------------------------------------------------------
    def open_inbox(self):
        if os.path.exists(INBOX):
            spawn("xdg-open", INBOX)
        else:
            spawn(QUICKNOTE)        # makes the inbox with the first note

    def say(self, text):
        self.error.set_text(text)
        self.error.set_visible(bool(text))

    def delete(self, note, button):
        key = (note["index"], note["raw"])
        if self.armed != key:
            self.armed = key
            button.set_label("Delete?")
            GLib.timeout_add_seconds(4, lambda: (self.disarm(key, button), False)[1])
            return
        self.armed = None
        text = read_inbox()
        new = remove_note(text or "", note["index"], note["raw"])
        if new is None:
            self.say("!  That note is no longer in the inbox (edited elsewhere?)")
        else:
            try:
                write_inbox(new)
                self.say("")
            except OSError as exc:
                self.say(f"!  Could not write the inbox: {exc}")
        self.refresh()

    def disarm(self, key, button):
        if self.armed == key:
            self.armed = None
            button.set_label("Delete")

    # -- drawing ---------------------------------------------------------------------
    def refresh(self):
        background(read_inbox, self.draw)

    def draw(self, text):
        clear(self.rows)
        home = os.path.expanduser("~")
        shown_path = "~" + INBOX[len(home):] if INBOX.startswith(home + os.sep) else INBOX
        if text is None:
            self.summary.set_text(f"empty: nothing noted yet ({shown_path} is made with the first note)")
            self.widget.show_all()
            return
        notes = parse_inbox(text)
        memos = sum(1 for n in notes if n["memo"])
        self.summary.set_text(f"{len(notes)} note{'s' * (len(notes) != 1)}"
                              + (f", {memos} of them voice memos" if memos else "") + f"  ·  {shown_path}")
        import datetime as dt
        today = dt.date.today().isoformat()
        for note in list(reversed(notes))[:SHOWN]:
            buttons = []
            if note["memo"]:
                buttons.append(link("Play", lambda p=note["memo"]: spawn("xdg-open", p)))
                txt = os.path.splitext(note["memo"])[0] + ".txt"
                if os.path.exists(txt):
                    buttons.append(link("Text", lambda p=txt: spawn("xdg-open", p)))
            delete = Gtk.Button(label="Delete")
            delete.get_style_context().add_class("ctl-link")
            delete.connect("clicked", lambda b, n=note: self.delete(n, b))
            buttons.append(delete)
            icon = "" if note["memo"] else ""
            grid, _ = row(icon, short(note["text"], 90) or "(empty)", note_sub(note, today), links_row(*buttons))
            self.rows.pack_start(grid, False, False, 0)
        if not notes:
            self.rows.pack_start(dp.label("No notes in the inbox.", "ctl-sub"), False, False, 0)
        elif len(notes) > SHOWN:
            self.rows.pack_start(dp.label(f"{len(notes) - SHOWN} older ones: Open the inbox.", "ctl-sub"),
                                 False, False, 0)
        self.widget.show_all()
