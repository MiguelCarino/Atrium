"""Settings page: Theme > Gallery -- every desktop theme as a picture, to see
what it looks like BEFORE switching to it; a click switches.

The last tab of Theme (order 40: after Ambient 20 and Effects 30, which
test_settings_search pins as the tabs right after Theme). One card per
theme, in theme.py themes() order (order= then name, so a theme folder
added later shows up by itself): its preview, its name, and a line about it (theme.conf's header, else themes/README). The current theme's card
is lit (.active) and its name carries a check mark, in words as well as
colour, as the Theme tab's chips do. Lit means a ring and a faint accent wash
(button.dev-pick.theme-card.active in waybar/panel.css), not the solid fill
every other .active pick gets: a whole card in the accent was a large light
field on the HDR screen and hid the card's own labels (lofi: 1.03:1).

The previews come from make-theme-previews.py -- drawn from each theme's own
files (its first wallpaper for the primary screen, a mock bar and panel card
in its colours and font), never by switching the live theme, cached in
~/.cache/theme-previews/ and remade only when a theme's files change. The
page draws the cards at once (blank pictures while it waits), then makes the
stale previews one by one in a background thread and fills each in as it
lands: all nine from cold took 0.88 s here, after that only the mtime check.

A click runs the same switch as the Theme tab's chips: `theme.py set <name>`,
then panelui.load_css() so this window takes the new look with the rest of
the desktop (display_panel.DisplayControls.set_theme). In a thread here,
because a switch with the fade on takes a couple of seconds and the window
must not freeze; the cards are greyed out until it is done.

While a SEASONAL theme is current (seasons/: theme.py's "Seasonal themes"),
a Seasons row sits over the cards: Hemisphere [Auto / North / South] and
Season [Follow the date / Spring / Summer / Autumn / Winter], each running
`theme.py season hemisphere ...` / `theme.py season pin ...` (which
re-applies at once), and a caption from theme.season_status() -- the same
dict `theme.py season --json` prints: "Autumn · northern hemisphere, from
the weather place · winter from 1 Dec". Only north/south and the source word
ever show, never a place. Hidden for every other theme.
"""
import importlib.util
import os
import threading

# common first: it pins Gtk/Gdk to 3.0 before anything imports them.
from .common import *  # noqa: F401,F403  (the shared helpers and paths)

import gi  # noqa: E402

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, GLib, Gtk  # noqa: E402

import panelui  # noqa: E402  (load_css after a switch; waybar/scripts is on the path via common)

PAGE = {"id": "themes", "title": "Theme gallery", "icon": "", "group": "Look", "order": 40,
        "parent": "theme", "tab": "Gallery",
        "keywords": ["theme gallery", "gallery", "preview", "theme preview", "themes", "switch theme",
                     "change theme", "look", "temas", "galeria", "vista previa"]}

THEMES = os.path.join(HYPR, "theme.py")
CARDS_PER_LINE = 3      # 2 in the 1000 px window (rules.lua's size), 3 when it is made wider
# The width a preview is SHOWN at. The pictures are drawn at previews.SIZE
# (360 x 180), but a card is the picture plus the pick's padding (9 px a side
# in lofi) plus flowboxchild's 3 px: 384 px, two of them and the 8 px spacing
# 776 px -- and the 1000 px window leaves the page about 670 px, so the
# gallery was ONE column with 300 px empty beside it. At 290 px two cards
# take ~636 px with room for the fattest pick padding (win95's bevels).
SHOWN_W = 290


def shown_size(size, width=SHOWN_W):
    """(w, h) a preview of size (w, h) is shown at: width wide, the same
    aspect, never scaled UP (a smaller picture stays as drawn)."""
    w, h = size
    if w <= width:
        return w, h
    return width, max(1, round(h * width / w))


def _load_previews():
    spec = importlib.util.spec_from_file_location("make_theme_previews",
                                                  os.path.join(HYPR, "make-theme-previews.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


previews = _load_previews()


# -- what the page shows (no GTK, for the tests) ------------------------------------------
def card_rows(themes, current, about=None):
    """[{name, label, about, current}] for themes [(name, label)] -- the
    cards, in that order."""
    about = about or (lambda _n: "")
    return [{"name": n, "label": label, "about": about(n), "current": n == current} for n, label in themes]


def title_markup(row):
    """The card's name: a check mark on the current theme (not colour
    alone: a lit and an unlit card can look alike in some themes)."""
    text = GLib.markup_escape_text(row["label"])
    return f"✓ {text}" if row["current"] else text


def status_text(rows, switching=None):
    if switching:
        return f"Switching to {switching}…"
    now = next((r["label"] for r in rows if r["current"]), "")
    return (f"Now: {now}. " if now else "") + "Click a theme to switch to it."


HEMI_CHOICES = (("auto", "Auto"), ("north", "North"), ("south", "South"))
SEASON_CHOICES = (("auto", "Follow the date"), ("spring", "Spring"), ("summer", "Summer"),
                  ("autumn", "Autumn"), ("winter", "Winter"))
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def season_caption(status):
    """theme.season_status() as the Seasons row's line, or "" for a theme
    that is not seasonal: "Autumn · northern hemisphere, from the weather
    place · winter from 1 Dec", or "... · pinned" while a season is held."""
    if not status or not status.get("seasonal"):
        return ""
    import theme as T
    hemi = status.get("hemisphere") or "north"
    where = f"{hemi}ern hemisphere, {T.SOURCE_WORDS.get(status.get('source'), status.get('source') or '')}"
    head = f"{(status.get('season') or '').capitalize()} · {where.rstrip(', ')}"
    if status.get("pin"):
        return f"{head} · pinned"
    nxt = status.get("next") or {}
    try:
        _y, m, d = (int(x) for x in (nxt.get("date") or "").split("-"))
        return f"{head} · {nxt['season']} from {d} {MONTHS[m - 1]}"
    except (ValueError, IndexError, KeyError):
        return head


def season_choices(status):
    """(hemisphere id, season id) the two selectors show: the hemisphere
    only when you set it (source "setting"; otherwise it is Auto, whatever
    auto resolved to), the season only when one is pinned."""
    status = status or {}
    hemi = status.get("hemisphere") if status.get("source") == "setting" else "auto"
    return hemi or "auto", status.get("pin") or "auto"


def gather_season():
    """season_status() for the current theme: runs in a thread (auto may
    read the weather place from region.py's cache)."""
    import theme as T
    return T.season_status()


def gather():
    """The cards' data (no previews made yet): runs in a thread."""
    import theme as T          # scripts/ is on the path (settings.py, the tests)
    return card_rows(T.themes(), T.current(), previews.about)


class Page:
    def __init__(self):
        self.widget = page_box()
        w = self.widget
        self.rows = []
        self.cards = {}             # name -> (button, image, title label)
        self.generation = 0         # a newer refresh drops an older one's late results
        self.switching = None
        self.quiet = False          # set while the selectors are filled from the status

        w.pack_start(heading("THEMES"), False, False, 0)
        self.hemi = self.selector(HEMI_CHOICES, "hemisphere")
        self.season = self.selector(SEASON_CHOICES, "pin")
        picks = Gtk.Box(spacing=8)
        picks.pack_start(self.hemi, False, False, 0)
        picks.pack_start(self.season, False, False, 0)
        self.season_row, self.season_sub = row("\uf06c", "Seasons", "", picks)     # Font Awesome's leaf
        self.season_row.set_no_show_all(True)
        w.pack_start(self.season_row, False, False, 0)
        self.status = label("", "ctl-sub")
        self.status.set_line_wrap(True)
        w.pack_start(self.status, False, False, 0)

        self.grid = Gtk.FlowBox()
        self.grid.set_selection_mode(Gtk.SelectionMode.NONE)
        self.grid.set_homogeneous(True)
        self.grid.set_max_children_per_line(CARDS_PER_LINE)
        self.grid.set_column_spacing(8)
        self.grid.set_row_spacing(8)
        self.grid.set_valign(Gtk.Align.START)
        w.pack_start(self.grid, False, False, 0)

        self.note = label("", "ctl-sub")
        self.note.set_line_wrap(True)
        self.note.set_max_width_chars(90)
        self.note.set_text("Each picture is drawn from the theme's own files -- its first wallpaper for the "
                           "main screen, a bar and a panel in its colours and font -- without switching to it. "
                           f"Kept in {previews.CACHE}, redrawn when a theme's files change "
                           "(make-theme-previews.py --force redraws them all).")
        w.pack_start(details(self.note), False, False, 0)

    # -- the Seasons row -----------------------------------------------------------------
    def selector(self, choices, verb):
        combo = Gtk.ComboBoxText()
        for key, text in choices:
            combo.append(key, text)
        combo.connect("changed", lambda c, v=verb: self.pick_season(v, c.get_active_id()))
        return combo

    def show_season(self, status):
        """Fill the Seasons row from a season_status(), shown only while the
        current theme is seasonal."""
        caption = season_caption(status)
        if not caption:
            self.season_row.hide()
            return
        self.quiet = True
        hemi, pin = season_choices(status)
        self.hemi.set_active_id(hemi)
        self.season.set_active_id(pin)
        self.quiet = False
        self.season_sub.set_text(caption)
        self.season_row.set_no_show_all(False)
        self.season_row.show_all()

    def pick_season(self, verb, value):
        if self.quiet or not value:
            return
        self.hemi.set_sensitive(False)
        self.season.set_sensitive(False)

        def done(_out):
            self.hemi.set_sensitive(True)
            self.season.set_sensitive(True)
            panelui.load_css()      # a pin re-applies the theme: follow its new colours
            background(gather_season, self.show_season)
        background(lambda: run(THEMES, "season", verb, value, timeout=60), done)

    # -- drawing -------------------------------------------------------------------------
    def card(self, row):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        image = Gtk.Image()
        image.set_size_request(*shown_size(previews.SIZE))
        image.set_halign(Gtk.Align.START)     # over the name and the line, not centred in the card
        box.pack_start(image, False, False, 0)
        title = label("", "ctl-title")
        box.pack_start(title, False, False, 0)
        about = label(row["about"], "ctl-sub")
        about.set_line_wrap(True)
        about.set_max_width_chars(40)
        about.set_lines(2)
        box.pack_start(about, False, False, 0)
        button = Gtk.Button()
        button.add(box)
        button.get_style_context().add_class("dev-pick")
        button.get_style_context().add_class("theme-card")     # its own .active (panel.css)
        button.set_tooltip_text(f"Switch to {row['label']}")
        button.connect("clicked", lambda _b, n=row["name"], lab=row["label"]: self.switch(n, lab))
        return button, image, title

    def draw(self, rows):
        """Cards for rows (rebuilt only when the list of themes changes; the
        current mark always)."""
        self.rows = rows
        if [r["name"] for r in rows] != list(self.cards):
            clear(self.grid)
            self.cards = {}
            for row in rows:
                self.cards[row["name"]] = self.card(row)
                self.grid.add(self.cards[row["name"]][0])
            self.grid.show_all()
        for row in rows:
            button, _image, title = self.cards[row["name"]]
            title.set_markup(title_markup(row))
            (button.get_style_context().add_class if row["current"]
             else button.get_style_context().remove_class)("active")
            button.set_sensitive(not self.switching)
        self.status.set_text(status_text(rows, self.switching))

    def show_preview(self, name, path):
        card = self.cards.get(name)
        if not card or not path:
            return
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
            w, h = shown_size((pixbuf.get_width(), pixbuf.get_height()))
            if w != pixbuf.get_width():
                # HYPER: GdkPixbuf's best filter, for the mock bar's small
                # text at 0.8x; one 360x180 picture per card, drawn once.
                pixbuf = pixbuf.scale_simple(w, h, GdkPixbuf.InterpType.HYPER)
            card[1].set_from_pixbuf(pixbuf)
        except GLib.Error:
            pass

    # -- data ----------------------------------------------------------------------------
    def refresh(self):
        self.generation += 1
        gen = self.generation
        background(gather, lambda rows: self.loaded(gen, rows))
        background(gather_season, lambda status: gen == self.generation and self.show_season(status))

    def loaded(self, gen, rows):
        if gen != self.generation:
            return
        self.draw(rows)
        names = [r["name"] for r in rows]

        def work():
            # One after the other (not a thread each): the machine is shared,
            # and the first cards fill in first.
            for name in names:
                if gen != self.generation:
                    return
                try:
                    path = previews.preview(name)
                except Exception:           # noqa: BLE001  (a broken theme: no picture, the rest still draw)
                    path = None
                GLib.idle_add(lambda n=name, p=path: (gen == self.generation and self.show_preview(n, p), False)[1])
        threading.Thread(target=work, daemon=True).start()

    def switch(self, name, title):
        if self.switching or any(r["current"] and r["name"] == name for r in self.rows):
            return
        self.switching = title
        self.draw(self.rows)

        def done(_out):
            self.switching = None
            panelui.load_css()      # this window's look follows the switch
            self.refresh()
        background(lambda: run(THEMES, "set", name, timeout=60), done)
