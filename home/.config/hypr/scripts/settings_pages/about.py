"""Settings page: About this computer -- what the machine is, from the
firmware up to the desktop theme (system-info.py).

First a card that says it at a glance, in the theme's colours (.about-hero
in waybar/panel.css): the system's logo and the computer's name, the system
and desktop on one line, the machine's model, and a tile each for the
processor, graphics, memory, storage, screens, desktop and uptime
(hero_facts(), from the same sections the details use). Under it "More
details" opens everything else -- the report buttons, the section index and
every section -- and closes it again; it opens closed each time.

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
TILES_PER_LINE = 4
FEDORA = "\uf798"       # Font Awesome 6 Brands: fedora (the logo when the system is Fedora)
LINUX = "\uf17c"        # ... linux, for any other


def first(section, name=None):
    """A section's first row, or its first row called `name`."""
    for r in (section or {}).get("rows", []):
        if name is None or r["name"] == name or r["name"].startswith(name + " "):
            return r
    return None


def size_bytes(text):
    """"8.00 TB" / "480 GB" -> bytes (0 when it is not a size)."""
    parts = (text or "").split()
    units = {"KB": 1e3, "MB": 1e6, "GB": 1e9, "TB": 1e12, "PB": 1e15}
    try:
        return float(parts[0]) * units[parts[1]] if len(parts) == 2 and parts[1] in units else 0
    except ValueError:
        return 0


def total_size(n):
    for unit, k in (("TB", 1e12), ("GB", 1e9)):
        if n >= k:
            return f"{n / k:.1f} {unit}".replace(".0 ", " ")
    return f"{n / 1e6:.0f} MB"


def hero_facts(data):
    """What the card shows, from the sections gathered so far ({id: section}):
    {"name", "system", "model", "logo", "tiles": [(key, icon, caption, value, sub)]}.
    A tile whose section has not answered yet is ("…") so the card keeps its shape."""
    comp, os_, cpu = data.get("computer"), data.get("os"), data.get("cpu")
    tiles = []
    r = first(cpu)
    tiles.append(("cpu", si.ICON["cpu"], "Processor",
                  (r["name"].replace(" Processor", "") if r else "…"), (r or {}).get("value", "")))
    r = first(data.get("gpu"))
    tiles.append(("gpu", si.ICON["gpu"], "Graphics", r["name"] if r else "…", (r or {}).get("value", "")))
    r = first(data.get("memory"), "RAM")
    swap = first(data.get("memory"), "Swap")
    tiles.append(("memory", si.ICON["memory"], "Memory", r.get("value", "") if r else "…",
                  f"swap {swap['value']}" if swap and swap.get("value") else ""))
    drives = [d for d in (data.get("storage") or {}).get("rows", []) if d.get("icon") == si.ICON["disk"]]
    total = sum(size_bytes(d.get("value")) for d in drives)
    tiles.append(("storage", si.ICON["disk"], "Storage", total_size(total) if total else
                  ("…" if "storage" not in data else "—"),
                  f"{len(drives)} drive{'s' if len(drives) != 1 else ''}" if drives else ""))
    screens = (data.get("displays") or {}).get("rows", [])
    screens = [d for d in screens if d.get("icon") == si.ICON["display"]]
    biggest = max(screens, key=lambda d: _pixels(d.get("value")), default=None)
    tiles.append(("displays", si.ICON["display"], "Screens",
                  f"{len(screens)} screen{'s' if len(screens) != 1 else ''}" if screens else
                  ("…" if "displays" not in data else "—"),
                  f"largest {biggest['value'].split(' @')[0]}" if biggest else ""))
    hypr = first(os_, "Hyprland")
    look = first(data.get("look"))
    tiles.append(("desktop", si.ICON["desktop"], "Desktop",
                  f"Hyprland {hypr['value']}" if hypr and hypr.get("value") else "…",
                  f"theme {look['name']}" if look else ""))
    kernel = first(os_, "Kernel")
    tiles.append(("kernel", si.ICON["kernel"], "Kernel",
                  (kernel.get("value", "").split("-")[0] if kernel else "…"),
                  kernel.get("value", "") if kernel else ""))
    up = first(comp, "Uptime")
    tiles.append(("uptime", si.ICON["clock"], "Up for", up.get("value", "") if up else "…",
                  (up.get("lines") or [""])[0] if up else ""))
    system = first(os_)
    model = first(comp)
    sysname = system["name"] if system else ""
    return {"name": si.socket.gethostname(),
            "system": sysname or "…",
            "model": model["name"] if model else "",
            "logo": FEDORA if "fedora" in sysname.lower() else LINUX,
            "tiles": tiles}


def _pixels(value):
    """"3440×1440 @ 60 Hz" -> 4953600."""
    try:
        w, h = (value or "").split(" @")[0].split("×")
        return int(w) * int(h)
    except ValueError:
        return 0


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
        outer = self.widget
        outer.pack_start(self.build_hero(), False, False, 0)
        self.more = link("More details  ▾", self.toggle_more)
        more_row = Gtk.Box()
        more_row.set_halign(Gtk.Align.CENTER)
        more_row.pack_start(self.more, False, False, 0)
        outer.pack_start(more_row, False, False, 0)
        self.details = page_box()
        self.details.set_no_show_all(True)
        outer.pack_start(self.details, False, False, 0)
        w = self.details
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

    # -- the card ----------------------------------------------------------------------------
    def build_hero(self):
        hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        hero.get_style_context().add_class("about-hero")
        top = Gtk.Box(spacing=18)
        self.logo = dp.label(FEDORA, "about-logo", 0.5)
        self.logo.set_valign(Gtk.Align.CENTER)
        top.pack_start(self.logo, False, False, 0)
        names = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        names.set_valign(Gtk.Align.CENTER)
        self.hero_name = dp.label(si.socket.gethostname(), "about-name")
        self.hero_system = dp.label("…", "about-system")
        self.hero_model = dp.label("", "about-model")
        for lab in (self.hero_name, self.hero_system, self.hero_model):
            lab.set_line_wrap(True)
            names.pack_start(lab, False, False, 0)
        top.pack_start(names, True, True, 0)
        hero.pack_start(top, False, False, 0)
        self.tiles = Gtk.Grid()             # two even rows of four
        self.tiles.set_column_homogeneous(True)
        self.tiles.set_column_spacing(8)
        self.tiles.set_row_spacing(8)
        self.tile_labels = {}
        for i, (key, icon, caption, _value, _sub) in enumerate(hero_facts({})["tiles"]):
            tile = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            tile.get_style_context().add_class("about-tile")
            head = Gtk.Box(spacing=6)
            head.pack_start(dp.label(icon, "about-tile-icon"), False, False, 0)
            head.pack_start(dp.label(caption.upper(), "about-cap"), False, False, 0)
            tile.pack_start(head, False, False, 0)
            value, sub = dp.label("…", "about-value"), dp.label("", "about-sub")
            for lab in (value, sub):
                lab.set_line_wrap(True)
                lab.set_max_width_chars(18)
                tile.pack_start(lab, False, False, 0)
            self.tile_labels[key] = (value, sub)
            self.tiles.attach(tile, i % TILES_PER_LINE, i // TILES_PER_LINE, 1, 1)
        hero.pack_start(self.tiles, False, False, 0)
        return hero

    def draw_hero(self):
        facts = hero_facts(self.data)
        self.logo.set_text(facts["logo"])
        self.hero_system.set_text(facts["system"])
        self.hero_model.set_text(facts["model"])
        self.hero_model.set_visible(bool(facts["model"]))
        for key, _icon, _caption, value, sub in facts["tiles"]:
            v, s = self.tile_labels[key]
            v.set_text(value)
            s.set_text(sub)
            s.set_visible(bool(sub))

    def toggle_more(self):
        show = not self.details.get_visible()
        self.details.set_no_show_all(not show)
        if show:
            self.details.show_all()
        else:
            self.details.hide()
        self.more.set_label("Fewer details  ▴" if show else "More details  ▾")

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
        self.draw_hero()
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
