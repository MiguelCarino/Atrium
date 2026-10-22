"""Settings page: About this computer -- what the machine is, from the
firmware up to the desktop theme (system-info.py).

Every section is gathered in its own thread when the page is shown and
fills in as soon as its own commands answer: the processor and memory in a
few milliseconds, the graphics card (nvidia-smi, vulkaninfo) and the
package counts (rpm -qa) in about a second. Until then a section says
"checking…"; on a later visit the old answer stays up while the new one is
gathered, so nothing jumps around.

The text the page shows is system-info.py's own rows, so "Copy all as text",
"Save report" and `system-info.py text` in a terminal say exactly the same
thing. MAC addresses, serial numbers and public IPv6 addresses stay hidden
(on the page and in what is copied or saved) until "Show identifiers" is
pressed -- a report is usually pasted somewhere public. That button is the
page's only state, and it is not a setting: it resets when the window closes.

The section index under the buttons jumps to a section: it scrolls the
Settings window's scroll (the page's ScrolledWindow ancestor) to that
section's heading. The computer's name is changed on the Network page
("Open Network" on the first row), where hostnamectl asks for the password.
"""
import importlib.util
import os

from gi.repository import GLib, Gtk  # noqa: F401

from .common import *  # noqa: F401,F403  (the shared helpers and paths)

PAGE = {"id": "about", "title": "About this computer", "icon": "\uf05a", "group": "System", "order": 90,
        "keywords": ["system information", "specs", "hardware", "computer", "model", "cpu", "processor", "gpu",
                     "graphics card", "nvidia", "driver", "ram", "memory", "disks", "kernel", "fedora",
                     "version", "os", "hostname", "motherboard", "bios", "firmware", "report",
                     "copy system info"]}

SYSINFO = os.path.join(HYPR, "system-info.py")
SETTINGS = os.path.join(HYPR, "settings.py")
INDEX_PER_LINE = 6      # jump buttons per line of the section index


def load_sysinfo():
    """system-info.py as a module (its name has a dash, so not a plain import)."""
    spec = importlib.util.spec_from_file_location("system_info", SYSINFO)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


si = load_sysinfo()


def tilde(path):
    """/home/me/Documents/x.txt -> ~/Documents/x.txt, for the status line."""
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if path == home or path.startswith(home + os.sep) else path


def row_sub(r, reveal):
    """A row's detail lines as the page shows them: the identifiers last,
    each as "label: hidden" until revealed."""
    lines = list(r.get("lines", []))
    for key, value in (r.get("secret") or {}).items():
        lines.append(f"{key}: {value if reveal else 'hidden'}")
    return "\n".join(lines)


class Page:
    def __init__(self):
        self.data = {}          # section id -> the last answer (what is on screen)
        self.pending = set()    # section ids being gathered right now
        self.reveal = False
        self.widget = page_box()
        w = self.widget
        # The computer's name is renamed on the Network page, so its row links there.
        self.head, self.head_sub = row("\uf390", si.socket.gethostname(), "checking…",
                                       link("Open Network", lambda: spawn(SETTINGS, "network")))
        self.head.set_tooltip_text("Rename this computer on the Network page")
        w.pack_start(self.head, False, False, 0)
        self.reveal_btn = link("Show identifiers", self.toggle_reveal)
        w.pack_start(links_row(link("Copy all as text", self.copy), link("Save report", self.save),
                               self.reveal_btn, link("Check again", self.refresh)), False, False, 0)
        self.status = Gtk.Box(spacing=8)
        w.pack_start(self.status, False, False, 0)
        # The section index: one jump button per section below.
        index = Gtk.FlowBox()
        index.set_selection_mode(Gtk.SelectionMode.NONE)
        index.set_max_children_per_line(INDEX_PER_LINE)
        index.set_homogeneous(True)
        w.pack_start(index, False, False, 0)
        self.boxes, self.headings = {}, {}
        for sid, title in si.SECTIONS:
            index.add(link(title, lambda s=sid: self.jump(s)))
            w.pack_start(sep(), False, False, 0)
            self.headings[sid] = heading(title.upper())
            w.pack_start(self.headings[sid], False, False, 0)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            w.pack_start(box, False, False, 0)
            self.boxes[sid] = box
        note = dp.label("Nothing here is sent anywhere. The same report in a terminal: "
                        "system-info.py text  (add --reveal for the identifiers).", "ctl-sub")
        note.set_line_wrap(True)
        w.pack_start(sep(), False, False, 0)
        w.pack_start(note, False, False, 0)

    # -- gathering ---------------------------------------------------------------------------
    def refresh(self):
        for sid, _title in si.SECTIONS:
            if sid in self.pending:
                continue
            box = self.boxes[sid]
            if not box.get_children():
                box.pack_start(dp.label("checking…", "ctl-sub"), False, False, 0)
                box.show_all()
            self.pending.add(sid)
            background(lambda s=sid: si.gather(s), self.arrived)

    def arrived(self, section):
        self.pending.discard(section["id"])
        self.data[section["id"]] = section
        self.draw(section["id"])
        self.head_sub.set_text(si.summary(self.ordered(), host=False) or "checking…")

    def ordered(self):
        return [self.data[s] for s, _ in si.SECTIONS if s in self.data]

    def jump(self, sid):
        """Scroll the window's page scroll so the section's heading is at
        the top (or as near as the page's end allows)."""
        scroll = self.widget.get_ancestor(Gtk.ScrolledWindow)
        where = self.headings[sid].translate_coordinates(self.widget, 0, 0)
        if scroll is None or where is None:
            return
        adj = scroll.get_vadjustment()
        adj.set_value(min(max(0, where[1] - 6), adj.get_upper() - adj.get_page_size()))

    # -- drawing -----------------------------------------------------------------------------
    def draw(self, sid):
        box = self.boxes[sid]
        clear(box)
        for r in self.data[sid]["rows"]:
            value = dp.label(r["value"], "ctl-value", 1.0) if r.get("value") else None
            grid, _sub = row(r.get("icon") or "\uf05a", r["name"], row_sub(r, self.reveal), value)
            title = grid.get_child_at(1, 0)
            title.set_line_wrap(True)
            title.set_max_width_chars(60)
            if r.get("error"):
                grid.get_style_context().add_class("error")
            box.pack_start(grid, False, False, 0)
        box.show_all()

    def toggle_reveal(self):
        self.reveal = not self.reveal
        self.reveal_btn.set_label("Hide identifiers" if self.reveal else "Show identifiers")
        for sid in self.data:
            self.draw(sid)

    def say(self, text, *buttons):
        clear(self.status)
        lab = dp.label(text, "ctl-sub")
        lab.set_line_wrap(True)
        lab.set_hexpand(True)
        self.status.pack_start(lab, True, True, 0)
        for b in buttons:
            self.status.pack_start(b, False, False, 0)
        self.status.show_all()

    # -- copy / save -------------------------------------------------------------------------
    def report(self, reveal):
        """The whole report's text, gathering what is not on the page yet
        (called in a thread, so `reveal` is passed in as it was at the click,
        not read from self while the button may be toggled)."""
        missing = [s for s, _ in si.SECTIONS if s not in self.data]
        sections = {s["id"]: s for s in self.ordered()}
        for s in si.gather_all(missing) if missing else []:
            sections[s["id"]] = s
        return si.report_text([sections[s] for s, _ in si.SECTIONS if s in sections], reveal)

    def copy(self):
        self.say("gathering…")
        reveal = self.reveal

        def work():
            text = self.report(reveal)
            return si.copy_text(text), len(text.splitlines())
        background(work, lambda res: self.say(
            f"Copied the report to the clipboard ({res[1]} lines, "
            f"{'with the identifiers' if reveal else 'identifiers left out'})." if res[0] else
            "Could not copy: wl-copy did not take it. Save report writes it to a file instead."))

    def save(self):
        self.say("gathering…")
        reveal = self.reveal

        def work():
            try:
                return si.save_report(self.report(reveal)), None
            except OSError as exc:
                return None, exc
        background(work, lambda res: self.saved(res, reveal))

    def saved(self, res, reveal):
        path, err = res
        if err is not None:
            self.say(f"Could not save the report: {err.strerror or err}")
            return
        self.say(f"Saved to {tilde(path)} ({'with the identifiers' if reveal else 'identifiers left out'}).",
                 link("Open it", lambda: spawn("xdg-open", path)),
                 link("Show the folder", lambda: spawn("xdg-open", os.path.dirname(path))))
