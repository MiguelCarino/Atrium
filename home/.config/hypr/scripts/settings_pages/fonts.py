"""Settings page: fonts, text rendering and the pointer (font-settings.py).

Four groups, each written everywhere it matters by font-settings.py (its
docstring has the full map) and read back from there on every redraw:

  FONTS IN APPS        interface, document, monospace (with sizes) and the
                       serif default: GTK3 / GTK4 / libadwaita (gsettings),
                       Qt (qt5ct / qt6ct), COSMIC apps, and fontconfig's
                       sans-serif / serif / monospace aliases for everything
                       that only asks for a generic family
  TEXT SIZE AND RENDERING
                       text scaling factor, antialiasing, hinting, subpixel
                       order (gsettings and fontconfig)
  THE DESKTOP'S OWN TEXT
                       the faces the desktop theme draws the bar, panels,
                       launcher, mako and the terminals in -- yours over every
                       theme (display.conf font_user..., read by theme.py),
                       or the theme's
  POINTER              cursor theme and size (gsettings, hyprctl setcursor,
                       and lua/env.lua / uwsm's env at the next login)
  MORE                 fonts folder, rescan, reset; where each choice went
                       (in a Details fold, as are the longer notes)

A font picker lists the INSTALLED families (fc-list, through font-settings.py
families) with a search entry; each one is drawn in its own face, so the
list is its own preview. It shows at most PICKER_ROWS at a time: every row is
a face pango has to load, and a few hundred at once would stall the window.
"""
from gi.repository import GLib, Gtk  # noqa: F401

from .common import *  # noqa: F401,F403  (the shared helpers and paths)

import os  # noqa: E402
import subprocess  # noqa: E402

PAGE = {"id": "fonts", "title": "Text & pointer", "icon": "", "group": "Look", "order": 30, "tab": "Fonts & text",
        # Words the search bar matches this page by (the cursor lives here, not on Accessibility).
        "keywords": ["font", "text", "size", "dpi", "hinting", "antialiasing", "cursor", "pointer",
                     "mouse pointer", "cursor size", "cursor theme", "terminal font", "fuente", "typeface",
                     "text size", "text scaling", "bigger text", "subpixel", "monospace", "interface font",
                     "document font", "serif"]}

FONTSET = os.path.join(HYPR, "font-settings.py")
FONT_DIR = os.path.expanduser("~/.local/share/fonts")
PICKER_ROWS = 60
SIZE_DEBOUNCE_MS = 600
SAMPLE = "The quick brown fox jumps over the lazy dog  0123456789  ÀÉÎõü  ¿¡ €"
SAMPLE_MONO = "fn main() { let x = 0x1F; }  // O0 Il1| == != -> =>"
SAMPLE_SERIF = "Reading text: “The quick brown fox jumps over the lazy dog.”"
SCALE_PRESETS = [(90, "90%"), (100, "100%"), (110, "110%"), (125, "125%"), (150, "150%"), (175, "175%"),
                 (200, "200%")]
CURSOR_SIZES = [16, 24, 32, 40, 48, 64, 96]
CONFIRM_S = 4              # how long "Reset everything here" waits for its second click
RESET_LABEL = "Reset everything here"


def markup(family, text, size=None):
    """Pango markup drawing `text` in `family` (the CSS font of the label
    is overridden by the span, so the theme cannot hide the preview)."""
    attrs = f'font_family="{GLib.markup_escape_text(family)}"'
    if size:
        attrs += f' size="{int(size * 1024)}"'
    return f"<span {attrs}>{GLib.markup_escape_text(text)}</span>"


def wrap(text):
    lab = dp.label(text, "ctl-sub")
    lab.set_line_wrap(True)
    lab.set_max_width_chars(90)
    return lab


class FontPicker:
    """Search entry, an "only monospaced" switch and the families, each in
    its own face. on_pick(family) when one is clicked."""

    def __init__(self, on_pick, mono=False, mono_only_toggle=True):
        self.on_pick = on_pick
        self.fams = {"all": [], "mono": []}
        self.current = None
        self.widget = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.widget.set_margin_start(36)
        top = Gtk.Box(spacing=8)
        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text("Search the installed fonts")
        self.search.set_hexpand(True)
        self.search.connect("search-changed", lambda _e: self.fill())
        top.pack_start(self.search, True, True, 0)
        self.mono = Gtk.CheckButton(label="Only monospaced")
        self.mono.set_active(mono)
        self.mono.connect("toggled", lambda _c: self.fill())
        if mono_only_toggle:
            top.pack_start(self.mono, False, False, 0)
        self.widget.pack_start(top, False, False, 0)
        self.count = dp.label("", "ctl-sub")
        self.widget.pack_start(self.count, False, False, 0)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(240)
        scroll.set_max_content_height(240)
        # Plain dev-pick buttons rather than a Gtk.ListBox: the panels'
        # stylesheet styles those in every theme; a ListBox came out as
        # GTK's white list with the theme's light text on it.
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        scroll.add(self.list)
        self.widget.pack_start(scroll, False, False, 0)

    def set_families(self, fams, current):
        changed = fams != self.fams or current != self.current
        self.fams, self.current = fams, current
        if changed:
            self.fill()

    def fill(self):
        clear(self.list)
        pool = self.fams["mono" if self.mono.get_active() else "all"]
        query = self.search.get_text().strip().casefold()
        hits = [f for f in pool if query in f.casefold()] if query else list(pool)
        if self.current in hits:
            # The current face first, so the list opens on it.
            hits.remove(self.current)
            hits.insert(0, self.current)
        shown = hits[:PICKER_ROWS]
        more = len(hits) - len(shown)
        self.count.set_text(f"{len(hits)} of {len(pool)} families"
                            + (f"  ·  showing the first {len(shown)}, type to narrow" if more else "")
                            + ("" if hits else "  ·  nothing matches"))
        for fam in shown:
            r = Gtk.Button()
            r.get_style_context().add_class("dev-pick")
            if fam == self.current:
                r.get_style_context().add_class("active")
            r.set_can_focus(False)
            r.connect("clicked", lambda _b, f=fam: self.on_pick(f))
            box = Gtk.Box(spacing=12)
            box.set_margin_top(2)
            box.set_margin_bottom(2)
            name = dp.label(fam + ("  ✓" if fam == self.current else ""), "ctl-title")
            name.set_width_chars(26)
            name.set_max_width_chars(26)
            name.set_ellipsize(3)        # Pango.EllipsizeMode.END
            box.pack_start(name, False, False, 0)
            sample = dp.label("", "ctl-sub")
            sample.set_markup(markup(fam, "The quick brown fox 0123 Aa Gg"))
            sample.set_ellipsize(3)
            sample.set_hexpand(True)
            box.pack_start(sample, True, True, 0)
            r.add(box)
            self.list.pack_start(r, False, False, 0)
        self.list.show_all()


class FontRow:
    """One font setting: icon, title, what it is now (and where it goes),
    a live sample in the face, a size, Change… (opens a FontPicker under
    it) and a reset link. The page hands it set_* callbacks; the row never
    keeps a value of its own past a redraw."""

    def __init__(self, page, icon, title, sample, on_family, on_size=None, on_reset=None,
                 reset_label="Default", mono=False, mono_toggle=True, size_range=(4, 72, 0.5), px=False):
        self.page, self.sample_text = page, sample
        self.sample_pt = 0.75 if px else 1.0     # the terminal's size is px: the sample takes points
        self.on_family, self.on_size = on_family, on_size
        self.updating, self.pending = False, None
        self.widget = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        controls = Gtk.Box(spacing=6)
        self.spin = None
        if on_size:
            lo, hi, step = size_range
            self.spin = Gtk.SpinButton.new_with_range(lo, hi, step)
            self.spin.set_digits(1 if step < 1 else 0)
            self.spin.set_width_chars(4)
            self.spin.set_tooltip_text("Size")
            self.spin.connect("value-changed", self.size_changed)
            controls.pack_start(self.spin, False, False, 0)
        self.change = link("Change…", self.toggle)
        controls.pack_start(self.change, False, False, 0)
        if on_reset:
            controls.pack_start(link(reset_label, on_reset), False, False, 0)
        self.grid, self.sub = row(icon, title, "", controls)
        self.sample = dp.label("", "ctl-sub")
        self.sample.set_ellipsize(3)
        self.sample.set_hexpand(True)
        self.grid.attach(self.sample, 1, 2, 2, 1)
        self.widget.pack_start(self.grid, False, False, 0)
        self.picker = FontPicker(self.picked, mono=mono, mono_only_toggle=mono_toggle)
        self.revealer = Gtk.Revealer()
        self.revealer.add(self.picker.widget)
        self.widget.pack_start(self.revealer, False, False, 0)

    def toggle(self):
        open_ = not self.revealer.get_reveal_child()
        self.revealer.set_reveal_child(open_)
        self.change.set_label("Close" if open_ else "Change…")
        if open_:
            self.picker.search.grab_focus()

    def picked(self, family):
        self.revealer.set_reveal_child(False)
        self.change.set_label("Change…")
        self.on_family(family)

    def size_changed(self, spin):
        if self.updating:
            return
        if self.pending:
            GLib.source_remove(self.pending)
        self.pending = GLib.timeout_add(SIZE_DEBOUNCE_MS, self.commit_size)

    def commit_size(self):
        self.pending = None
        value = self.spin.get_value()
        self.on_size(f"{value:g}")
        return False

    def show(self, family, size, sub, fams):
        """Redraw from what the system reports: the face, its size (points,
        or px for the terminal), the sub line."""
        self.sub.set_text(sub)
        if family:
            pt = size * self.sample_pt if size else None
            self.sample.set_markup(markup(family, self.sample_text, pt if pt and pt <= 40 else None))
        else:
            self.sample.set_text("")
        if self.spin and size and self.pending is None:
            self.updating = True
            self.spin.set_value(size)
            self.updating = False
        self.picker.set_families(fams, family)


class Page:
    def __init__(self):
        self.fams = None
        self.data = None
        self.busy = 0
        self.updating = False
        self.confirm = None       # the GLib source while the reset waits for its second click
        self.widget = page_box()
        w = self.widget

        self.status = dp.label("", "ctl-sub")
        w.pack_start(self.status, False, False, 0)

        # -- fonts in apps --------------------------------------------------------
        w.pack_start(heading("FONTS IN APPS"), False, False, 0)
        self.rows = {
            "interface": FontRow(self, "", "Interface", SAMPLE,
                                 lambda f: self.do("set", "interface", f),
                                 lambda s: self.do("size", "interface", s),
                                 lambda: self.do("set", "interface", "default")),
            "document": FontRow(self, "", "Document", SAMPLE_SERIF,
                                lambda f: self.do("set", "document", f),
                                lambda s: self.do("size", "document", s),
                                lambda: self.do("set", "document", "default")),
            "monospace": FontRow(self, "", "Monospace", SAMPLE_MONO,
                                 lambda f: self.do("set", "monospace", f),
                                 lambda s: self.do("size", "monospace", s),
                                 lambda: self.do("set", "monospace", "default"), mono=True),
            "serif": FontRow(self, "", "Serif", SAMPLE_SERIF,
                             lambda f: self.do("set", "serif", f), None,
                             lambda: self.do("set", "serif", "default")),
        }
        for key in ("interface", "document", "monospace", "serif"):
            w.pack_start(self.rows[key].widget, False, False, 0)
        w.pack_start(details(wrap("Interface: menus, buttons and labels in GTK, libadwaita, Qt and COSMIC apps, and "
                          "the sans-serif default for everything else (Hyprland's own messages, web pages "
                          "that ask for sans-serif). Document: the text libadwaita and GNOME apps show for "
                          "reading. Monospace: code and terminals inside apps, and the monospace default. "
                          "Serif: what web pages and documents that ask for \"serif\" get. Sizes are in "
                          "points. Apps that are open follow at once (GTK, libadwaita) or when they next "
                          "start (Qt, COSMIC, most others).")), False, False, 0)
        w.pack_start(sep(), False, False, 0)

        # -- text size and rendering ---------------------------------------------
        w.pack_start(heading("TEXT SIZE AND RENDERING"), False, False, 0)
        self.scale = Slider("scale", "Text scaling", 50, 300, 5, "%",
                            lambda _k, v: self.do("scale", f"{v / 100:.2f}"))
        w.pack_start(self.scale.widget, False, False, 0)
        self.scale_chips = Chips(lambda v: self.do("scale", f"{v / 100:.2f}"))
        self.scale_chips.widget.set_max_children_per_line(7)
        w.pack_start(self.scale_chips.widget, False, False, 0)
        self.render_rows = {}
        for key, icon, title, items in (
                ("antialias", "", "Antialiasing",
                 [("none", "Off (sharp, jagged)"), ("grayscale", "Grayscale"), ("rgba", "Subpixel (LCD)")]),
                ("hinting", "", "Hinting",
                 [("none", "None"), ("slight", "Slight"), ("medium", "Medium"), ("full", "Full")]),
                ("subpixel", "", "Subpixel order",
                 [("rgb", "RGB"), ("bgr", "BGR"), ("vrgb", "Vertical RGB"), ("vbgr", "Vertical BGR")])):
            chips = Chips(lambda v, k=key: self.do(k, v))
            grid, sub = row(icon, title, "")
            grid.attach(chips.widget, 1, 2, 2, 1)
            chips.items = items
            self.render_rows[key] = (chips, sub)
            w.pack_start(grid, False, False, 0)
        w.pack_start(links_row(link("Back to automatic rendering", lambda: self.do("rendering", "default"))),
                     False, False, 0)
        self.render_sub = wrap("")
        w.pack_start(details(self.render_sub), False, False, 0)
        w.pack_start(sep(), False, False, 0)

        # -- the desktop's own text ---------------------------------------------
        w.pack_start(heading("THE DESKTOP'S OWN TEXT"), False, False, 0)
        self.desk = {
            "font": FontRow(self, "", "Bar, panels, launcher, notifications", SAMPLE,
                            lambda f: self.do("desktop", "font", f), None,
                            lambda: self.do("desktop", "font", "theme"), reset_label="Theme's"),
            "mono": FontRow(self, "", "Their monospaced text", SAMPLE_MONO,
                            lambda f: self.do("desktop", "mono", f), None,
                            lambda: self.do("desktop", "mono", "theme"), reset_label="Theme's", mono=True),
            "term": FontRow(self, "", "Terminals (COSMIC Terminal, kitty)", SAMPLE_MONO,
                            lambda f: self.do("desktop", "term", f),
                            lambda s: self.do("desktop", "term-size", str(int(float(s)))),
                            lambda: self.do_all([("desktop", "term", "theme"), ("desktop", "term-size", "theme")]),
                            reset_label="Theme's", mono=True, mono_toggle=False, size_range=(6, 48, 1), px=True),
        }
        for key in ("font", "mono", "term"):
            w.pack_start(self.desk[key].widget, False, False, 0)
        w.pack_start(links_row(link("Use the theme's fonts", lambda: self.do("desktop", "theme")),
                               link("Same as the apps", lambda: self.do("desktop", "apps"))), False, False, 0)
        self.desk_sub = wrap("")
        w.pack_start(details(self.desk_sub), False, False, 0)
        w.pack_start(sep(), False, False, 0)

        # -- pointer -----------------------------------------------------------------
        w.pack_start(heading("POINTER"), False, False, 0)
        self.cursor_row, self.cursor_sub = row("", "Cursor theme", "")
        self.cursor_chips = Chips(lambda v: self.do("cursor", v))
        self.cursor_row.attach(self.cursor_chips.widget, 1, 2, 2, 1)
        w.pack_start(self.cursor_row, False, False, 0)
        self.size_row, self.size_sub = row("", "Cursor size", "")
        self.size_chips = Chips(lambda v: self.do("cursor-size", str(v)))
        self.size_chips.widget.set_max_children_per_line(8)
        self.size_row.attach(self.size_chips.widget, 1, 2, 2, 1)
        w.pack_start(self.size_row, False, False, 0)
        w.pack_start(details(wrap("Set live in Hyprland (hyprctl setcursor), GTK apps (gsettings) and XWayland, and "
                          "kept for the next login (lua/env.lua and ~/.config/uwsm/env read the same choice for "
                          "XCURSOR_THEME / XCURSOR_SIZE). Apps that draw their own pointer pick a new size up "
                          "when they next start.")), False, False, 0)
        w.pack_start(sep(), False, False, 0)

        # -- where it went -----------------------------------------------------------
        w.pack_start(heading("MORE"), False, False, 0)
        self.reset_all = link(RESET_LABEL, self.on_reset)
        w.pack_start(links_row(link("Open the fonts folder", self.open_fonts),
                               link("Rescan installed fonts", self.rescan),
                               self.reset_all), False, False, 0)
        self.where = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        w.pack_start(details(self.where, label="Where it goes"), False, False, 0)

    # -- talking to font-settings.py ---------------------------------------------------
    def do(self, *args):
        self.do_all([args])

    def do_all(self, commands):
        """Run font-settings.py commands, one after the other, off the GTK
        thread, then redraw from what it reports. The last answer (or the
        first complaint) goes in the status line at the top."""
        self.busy += 1
        self.status.set_text("applying…")

        def work():
            said = ""
            for args in commands:
                try:
                    out = subprocess.run([FONTSET, *args], capture_output=True, text=True, timeout=60)
                except (OSError, subprocess.SubprocessError) as exc:
                    return f"Not changed: font-settings.py: {exc}"
                said = ((out.stdout.strip() or out.stderr.strip()).splitlines()[-1:] or [""])[0]
                if out.returncode:
                    # A refusal (a family that is not installed, a terminal
                    # font that is not monospaced...) says so, not "Last change".
                    return f"Not changed: {said.removeprefix('font-settings: ')}"
            return f"Last change: {said}" if said else ""

        def done(line):
            self.busy -= 1
            self.last = line
            self.refresh()
        background(work, done)

    def on_reset(self):
        """"Reset everything here" throws away every font, rendering and
        pointer choice at once (gsettings, qt?ct, COSMIC, fontconfig and the
        desktop's overrides), so it takes a second click within a few
        seconds, like the Windows page's reset."""
        if self.confirm is not None:
            self.cancel_confirm()
            self.do("reset")
            return
        self.reset_all.set_label("Reset every font, rendering and pointer setting? Click again")
        self.confirm = GLib.timeout_add_seconds(CONFIRM_S, self.cancel_confirm)

    def cancel_confirm(self):
        if self.confirm is not None:
            GLib.source_remove(self.confirm)
            self.confirm = None
        self.reset_all.set_label(RESET_LABEL)
        return False

    def open_fonts(self):
        os.makedirs(FONT_DIR, exist_ok=True)
        spawn("nautilus", FONT_DIR)

    def rescan(self):
        self.status.set_text("rescanning fonts…")
        self.fams = None
        background(lambda: run("fc-cache", "-f", FONT_DIR, timeout=120), lambda _r: self.refresh())

    def refresh(self):
        if not self.data:
            self.status.set_text("reading the font settings…")
        want_fams = self.fams is None
        background(lambda: (run_json(FONTSET, "status"),
                            run_json(FONTSET, "families", "--json") if want_fams else None),
                   self.show)

    # -- drawing --------------------------------------------------------------------------
    def show(self, data):
        status, fams = data
        if fams:
            self.fams = fams
        if not status:
            self.status.set_text("Font settings did not answer")
            return
        self.data = status
        fams = self.fams or {"all": [], "mono": []}
        last = getattr(self, "last", "")
        if not self.busy:
            self.status.set_text(last if last else
                                 "Changes apply at once and are kept.")

        roles, fc = status["roles"], status["fontconfig"]
        qt = status.get("qt") or {}
        cos = status.get("cosmic") or {}
        for key in ("interface", "document", "monospace"):
            r = roles[key]
            sub = f"{r['family']} {r['size']:g} pt" + ("  ·  the default" if r["default"] else "")
            self.rows[key].show(r["family"], r["size"], sub, fams)
        serif = roles["serif"]
        self.rows["serif"].show(serif["family"], None,
                                f"{serif['family'] or '?'}" + ("  ·  the system's choice" if serif["default"]
                                                                else "  ·  your choice"), fams)

        # rendering
        self.scale.show(round(status["scale"] * 100))
        pct = round(status["scale"] * 100)
        items = list(SCALE_PRESETS)
        if pct not in [p for p, _ in items]:
            items.append((pct, f"{pct}%"))
            items.sort()
        self.scale_chips.set(items, pct)
        rend = status["rendering"]
        manual = rend["mode"] == "manual"
        for key, (chips, sub) in self.render_rows.items():
            chips.set(chips.items, rend[key] if manual else None)
            if key == "subpixel":
                sub.set_text("only used with subpixel antialiasing" if rend["antialias"] != "rgba" else
                             "your screen's colour stripes (most are RGB)")
            elif key == "antialias":
                sub.set_text(f"now: {rend['antialias']}" if manual else
                             f"automatic (now {rend['antialias']})")
            else:
                sub.set_text(f"now: {rend['hinting']}" if manual else
                             f"automatic (now {rend['hinting']})")
        self.render_sub.set_text(
            ("Your rendering choices go to GTK (font-rendering=manual), libadwaita and fontconfig (Qt, kitty, "
             "Chrome, Firefox's pages)." if manual else
             "Automatic: GTK 4 picks rendering for each screen by itself (and ignores the three rows "
             "above until you choose one), Qt and the rest use fontconfig's system defaults.")
            + " A light stroke on a high-DPI screen suits slight hinting; at 1440p grayscale with slight "
            "hinting is the usual best. Subpixel order: OLED panels often are not RGB -- grayscale is the "
            "safe choice there.")

        # the desktop's own text
        desk = status["desktop"]
        for key in ("font", "mono", "term"):
            d = desk[key]
            first = (d["now"] or "").split(",")[0].strip()
            if d["user"]:
                sub = f"yours: {d['user']}  ·  the theme's: {d['theme']}"
            else:
                sub = f"the theme's ({desk['theme']}): {d['theme']}"
            size = None
            if key == "term":
                ts = desk["term-size"]
                size = float(ts["now"]) if (ts["now"] or "").isdigit() else None
                sub += f"  ·  {ts['now']} px" + ("" if ts["user"] else " (the theme's)")
            self.desk[key].show(first, size, sub, fams)
        self.desk_sub.set_text(
            f"These follow the desktop theme ({desk['theme']}) until you pick one; your pick stays through "
            "every theme switch, in front of the theme's own faces (a letter yours lacks still comes from "
            "the theme's). \"Same as the apps\" uses the interface and monospace faces above.")

        # pointer
        cur = status["cursor"]
        items = [("theme", f"Theme's ({cur['theme']})")] + [(n, n) for n in cur["installed"]]
        self.cursor_chips.set(items, cur["user"] or "theme")
        self.cursor_sub.set_text(f"now: {cur['now']}" + ("  ·  your choice" if cur["user"] else
                                                           "  ·  the desktop theme's"))
        sizes = sorted(set(CURSOR_SIZES) | {cur["size"]})
        self.size_chips.set([(s, f"{s}") for s in sizes], cur["size"])
        self.size_sub.set_text(f"{cur['size']} px" + ("  ·  the default" if cur["size"] == 24 else ""))

        # where it went
        clear(self.where)
        res = fc["resolved"]
        lines = [f"fontconfig: sans-serif → {res.get('sans-serif')}, serif → {res.get('serif')}, "
                 f"monospace → {res.get('monospace')}"
                 + (f"  ·  {fc['file'].replace(os.path.expanduser('~'), '~')}" if fc.get("file") else
                    "  ·  the system's defaults (no file of ours)")]
        for name in ("qt5", "qt6"):
            q = qt.get(name)
            if q is None:
                lines.append(f"{name}ct: not set up (no {name}ct.conf)")
            else:
                g, f = q.get("general"), q.get("fixed")
                lines.append(f"{name}ct: " + (f"{g[0]} {g[1]:g} pt" if g else "Qt's default") + ", fixed "
                             + (f"{f[0]} {f[1]:g} pt" if f else "Qt's default"))
        lines.append("COSMIC apps: " + (cos.get("interface") or "their default (Open Sans)") + ", "
                     + (cos.get("monospace") or "their default (Noto Sans Mono)"))
        lines.append(f"{len(fams['all'])} font families installed, {len(fams['mono'])} monospaced. New fonts: "
                     "put .ttf / .otf files in ~/.local/share/fonts, then Rescan.")
        for line in lines:
            self.where.pack_start(wrap(line), False, False, 0)
        self.widget.show_all()
