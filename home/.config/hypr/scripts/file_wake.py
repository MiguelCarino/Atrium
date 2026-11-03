#!/usr/bin/env python3
"""Sleep until a file changes (or a time is up): the inotify wait the
daemons that back off share, so that a longer sleep never makes them slow
to answer you.

Imported as a plain module (no dash in the name, like power_state.py) after
a script puts its own folder on sys.path. Standard library only: inotify is
reached through ctypes (libc's inotify_init1 / inotify_add_watch), as
voice.py's bar does -- no pyinotify, no inotifywait child.

    w = file_wake.Watch({folder: {"timers.json"}, other_folder: None},
                        masks={folder: file_wake.RENAMED})
    w.ok                  True when inotify is watching (else wait() only sleeps)
    w.wait(seconds)       -> True when a watched file changed, False when the
                             time ran out (or there is no inotify)
    w.drain()             -> the set of watched names that changed (empty:
                             none); ANY in it means "look again at everything"
    w.close()

Why folders and names, not files: the files these daemons care about are
written whole into a temporary file and renamed over the old one
(timers.json, the ring files, a poke file), and a watch on the file itself
would follow the old inode into oblivion at the first rename. A watch on the
folder sees the rename as IN_MOVED_TO with the new name, a plain write as
IN_CLOSE_WRITE, a removal as IN_DELETE; only the names asked for count (None
for a folder: any name in it). A folder that is not there yet is made first
-- an empty folder costs nothing, and without it the watch could not be set
at all (the caller's own folder: timers' ring folder, tasks' poke folder).

Why a mask per folder: a busy folder ($XDG_STATE_HOME/hypr holds
activity.jsonl, appended on every change of focus) would wake the sleeper
for each append only for the name filter to throw it away. A file that is
only ever written by rename (timers.json: timers.save() is a tmp file and
os.replace) needs only IN_MOVED_TO and IN_DELETE -- RENAMED -- and appends
to its neighbours then never reach the process at all. A file people edit
in place (tasks.json, in an editor) keeps the default MASK.

Why the kernel's own events are read too, not only names: a full queue
(IN_Q_OVERFLOW, wd -1) means some change was lost, so it counts as a hit on
everything (ANY) -- the caller takes a fresh look rather than sleeping
through it. A folder that goes away (IN_IGNORED after IN_DELETE_SELF, or
IN_MOVE_SELF: the watch would follow the old folder wherever it went) is
made and watched again, and that counts as a hit too, since whatever was
in it may have changed; if it cannot be watched again and no watch is left,
the fd closes and ok turns False, so the caller falls back to its short
period instead of a long sleep on a watch that is dead.

Why it falls back quietly: inotify can be missing (a container without it)
or out of watches (fs.inotify.max_user_watches used up by an IDE). Then
w.ok is False and wait() sleeps the whole time, and the caller -- which
knows what a missed change costs it -- uses its short period instead.
"""
import os
import select
import sys
import time

IN_CLOSE_WRITE, IN_MOVED_TO, IN_DELETE, IN_CREATE = 0x8, 0x80, 0x200, 0x100
IN_DELETE_SELF, IN_MOVE_SELF = 0x400, 0x800
IN_Q_OVERFLOW, IN_IGNORED = 0x4000, 0x8000
MASK = IN_CLOSE_WRITE | IN_MOVED_TO | IN_DELETE | IN_CREATE
RENAMED = IN_MOVED_TO | IN_DELETE       # for files only ever written by rename
SELF = IN_DELETE_SELF | IN_MOVE_SELF    # always added: the folder itself going away
ANY = "*"                               # drain(): a lost or re-made watch, look again


class Watch:
    """inotify on some folders, filtered to some names (see the module's
    docstring). Never raises: a watch that cannot be set leaves ok False."""

    def __init__(self, folders, masks=None):
        self.fd = None
        self.libc = None
        self.wanted = {}            # wd -> set of names, or None for any
        self.folder = {}            # wd -> (folder, mask), to watch it again
        masks = masks or {}
        try:
            import ctypes
            libc = ctypes.CDLL(None, use_errno=True)
            fd = libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
            if fd < 0:
                return
            self.libc = libc
            for folder, names in folders.items():
                wd = self._add(fd, folder, masks.get(folder, MASK))
                if wd < 0:
                    os.close(fd)
                    self.wanted, self.folder = {}, {}
                    return
                self.wanted[wd] = set(names) if names is not None else None
                self.folder[wd] = (folder, masks.get(folder, MASK))
            self.fd = fd
        except (OSError, AttributeError):
            self.fd = None

    def _add(self, fd, folder, mask):
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError:
            pass
        return self.libc.inotify_add_watch(fd, os.fsencode(folder), mask | SELF)

    @property
    def ok(self):
        return self.fd is not None

    def fileno(self):
        return self.fd

    def _rewatch(self, wd):
        """The folder behind WD went away (or moved): drop WD, make the
        folder and watch it again. Closes the fd when nothing is left."""
        names = self.wanted.pop(wd, set())
        folder, mask = self.folder.pop(wd, (None, MASK))
        if wd >= 0 and self.fd is not None:
            self.libc.inotify_rm_watch(self.fd, wd)     # IN_MOVE_SELF: the old one; harmless if gone
        if folder is not None and self.fd is not None:
            new = self._add(self.fd, folder, mask)
            if new >= 0:
                self.wanted[new] = names
                self.folder[new] = (folder, mask)
        if not self.wanted:
            self.close()

    def _matters(self, data):
        """The watched names DATA (raw inotify events) touches, as a set;
        ANY in it for an overflow or a folder that had to be watched again."""
        hits = set()
        i = 0
        while i + 16 <= len(data):
            wd = int.from_bytes(data[i:i + 4], sys.byteorder, signed=True)
            mask = int.from_bytes(data[i + 4:i + 8], sys.byteorder)
            length = int.from_bytes(data[i + 12:i + 16], sys.byteorder)
            name = data[i + 16:i + 16 + length].rstrip(b"\0").decode("utf-8", "replace")
            i += 16 + length
            if mask & IN_Q_OVERFLOW:
                hits.add(ANY)
                continue
            if wd not in self.wanted:
                continue            # a watch already dropped (the IN_IGNORED after a rewatch)
            if mask & (IN_IGNORED | IN_MOVE_SELF):
                self._rewatch(wd)
                hits.add(ANY)
                continue
            if mask & IN_DELETE_SELF:
                continue            # IN_IGNORED follows: handled there
            names = self.wanted[wd]
            if names is None or name in names:
                hits.add(name)
        return hits

    def drain(self):
        """Read what is queued: the set of watched names it touches (empty
        when none -- falsy, so `if w.drain():` reads as before)."""
        hits = set()
        while self.fd is not None:
            try:
                data = os.read(self.fd, 65536)
            except BlockingIOError:
                break
            except OSError:
                break
            if not data:
                break
            hits |= self._matters(data)
        return hits

    def wait(self, seconds):
        """Sleep up to SECONDS; True as soon as a watched file changes."""
        seconds = max(0.0, float(seconds))
        if self.fd is None:
            time.sleep(seconds)
            return False
        end = time.monotonic() + seconds
        while True:
            left = end - time.monotonic()
            if left <= 0:
                return False
            try:
                ready = select.select([self.fd], [], [], left)[0]
            except InterruptedError:
                continue
            if ready and self.drain():
                return True

    def close(self):
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None
