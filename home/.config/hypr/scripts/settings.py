#!/usr/bin/env python3
"""Settings: one window for the desktop's own settings (SUPER+I, the
launcher's "Settings" and "Settings: <page>" items, the toolbox).

    settings.py                   open it on the last page used
    settings.py <page>            open it on that page (an id from --list)
    settings.py <words>           not an id: the words go into the search box
                                  and the best page they find opens
                                  ("settings.py bluetooth" -> Network &
                                  Bluetooth, the other matches listed)
    settings.py --list [words] [--json]
                                  the pages (or the ones the words find, best
                                  first): id, group, title -- and with --json
                                  the icon, order and keywords too. Reads the
                                  pages' sources, no window, no GTK
    settings.py --render <page> <out.png> [seconds]
                                  one page drawn offscreen into a PNG, for
                                  checking a page without the screens
    settings.py --render-window <out.png> [seconds] [words]
                                  the whole window (sidebar, search) offscreen,
                                  with the words typed into the search box

The sidebar, by group (common.GROUPS order; each page says its own group and
order in its PAGE, see settings_pages/common.py):

    SMART     Smart desktop      every smart feature on one page: its switch,
                                 status, keys, a link to its own page, and
                                 "privacy at a glance" (settings_pages/
                                 intelligence.py; the logic is _smart.py)
    DISPLAY   Screens            HDR, brightness / warmth / saturation and
                                 refresh rate per screen (the display panel's
                                 own controls, waybar/scripts/display_panel.py
                                 DisplayControls)
    LOOK      Theme              theme, accent, window glass, moving / living
                                 wallpaper, fade, by time of day
              Wallpaper & lock screen   each screen's picture and the
                                 slideshow, the lock screen's look
                                 (wallpaper-slideshow.py, lock-screen.py)
              Effects            screen filters, animation presets
              Fonts, text & pointer   fonts in apps and in the desktop's own
                                 text, text size and rendering, the cursor
              Windows & workspaces    gaps, borders, corners, blur, shadow,
                                 dimming, tiling layout (window-look.py)
              Accessibility      magnifier, screen reader, high contrast,
                                 reduce motion / transparency, visual alerts,
                                 a larger pointer (accessibility.py)
              Bar & toolbox      which pills, in what order, on which screen,
                                 how often they look again (bar-settings.py)
    APPS      Default apps       what opens links, mail, folders, files...,
                                 the terminal (default-apps.py)
              Timers & alarms    what is set, the ring, calendar alarms, work
                                 hours (timers.py, workhours.py)
              Screenshots & recording   folders, formats, sound, instant
                                 replay, OCR, gamemode and game profiles
                                 (capture-settings.py)
    HARDWARE  Network & Bluetooth   wired, Wi-Fi, VPN, Bluetooth, airplane
                                 mode, the host name (network-settings.py)
              Sound              outputs, inputs, app volumes, profiles,
                                 over-amplification (sound-settings.py)
              Keyboard, mouse & touchpad   layouts, typing, pointer, touchpad,
                                 focus (input-settings.py)
              Keyboard shortcuts   every key bind, changing one, shortcuts of
                                 your own (shortcuts.py, lua/userbinds.lua)
              Devices            USB drives (automount.py), the phone
                                 (phone.py), game profiles (game-profiles.py)
    SAFETY    Emergency alerts   your place, the sources for your country, a
                                 drill (emergency-alerts.py)
              Privacy            activity / clipboard history, Ask your
                                 desktop, recent files, what is in use now
                                 (privacy_settings.py)
    SYSTEM    Notifications      Do Not Disturb, quiet hours, popups, theme
                                 sounds, history (notify-settings.py)
              Power & screen lock   idle timings, Keep awake, power profile,
                                 the session buttons (idle-settings.py)
              Storage            how full the disks are, what is big in ~,
                                 trash, caches, automatic clean-up, USB
                                 drives (storage.py, automount.py)
              Users, sharing & printers   you, the login screen, online
                                 accounts, firewall / SSH / encryption, the
                                 printers (accounts.py; root steps are copied,
                                 never run)
              Date, time & region   time zone, network time, the bar's clock,
                                 calendar, weather (region.py)
              Startup & background   services, timers, autostart apps
                                 (startup.py)
              Software updates   what is waiting, restart, history, firmware
                                 (software-updates.py)
              Maintenance        health (doctor.py), snapshots, the dotfiles
                                 backup, config safe mode (hypr-guard.py)
              About this computer   hardware and software (system-info.py)

A new module in settings_pages/ with a PAGE shows up by itself, in its group;
`settings.py --list` is always the real list.

The search box at the top of the sidebar (or just start typing; Ctrl+F goes
there too) filters the pages by their title and by the keywords each page
declares (PAGE["keywords"]): "bluetooth", "tap to click", "hdr", "time zone",
"sonido". While something is typed the sidebar is the matches, best first,
each with the keyword that found it when the title does not say it; Enter
opens the first, Esc empties the box (a second Esc closes the window). The
rules are settings_pages/_catalog.py's, which the launcher uses too, so a
word that finds a page here finds "Settings: <page>" there.

Nothing here holds settings of its own: every control runs the same command
the panel, the launcher or the keys run, and redraws from what that command
reports -- so this window, the bar's panels and the search bar always agree.
One instance: opening it again brings the open one forward (Gtk.Application).
Slow checks (the health check, Chrome-sized feeds) run in a thread; the
window never waits on them.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from settings_pages import _catalog  # noqa: E402  (no GTK: the page list and the search rules)


def list_pages(args):
    """settings.py --list [words] [--json]: from the pages' sources, so it
    answers in a few ms and works without a display."""
    as_json = "--json" in args
    query = " ".join(a for a in args if a != "--json")
    pages = _catalog.read_pages()
    if query:
        pages = _catalog.search(pages, query)
    if as_json:
        print(json.dumps([dict(p, hint=_catalog.hint(p, query)) if query else p for p in pages],
                         ensure_ascii=False, indent=1))
        return
    for p in pages:
        extra = _catalog.hint(p, query) if query else ""
        print(f"{p['id']:<14}{p.get('group', ''):<10}{p['title']}" + (f"   ({extra})" if extra else ""))


if __name__ == "__main__" and sys.argv[1:2] == ["--list"]:
    list_pages(sys.argv[2:])
    sys.exit(0)

import importlib  # noqa: E402
import pkgutil  # noqa: E402

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from settings_pages import common  # noqa: E402  (also puts waybar/scripts on the path)
import display_panel as dp  # noqa: E402  (DisplayControls)
import panelui  # noqa: E402  (the theme's panel stylesheet)
import settings_pages  # noqa: E402

APP_ID = "desktop.settings"         # also the Wayland app id: lua/rules.lua floats it
STATE = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                     "hypr", "settings-page")
BUILTIN = _catalog.BUILTIN          # the display panel's own three pages, listed like the rest


class DisplayPage:
    """One of DisplayControls' pages; all three share one DisplayControls."""
    controls = None

    def __init__(self, key):
        if DisplayPage.controls is None:
            DisplayPage.controls = dp.DisplayControls(Gtk.Box(), tabs=False)
        self.widget = DisplayPage.controls.pages[key]

    def refresh(self):
        DisplayPage.controls.refresh()


def discover():
    """[(meta, factory)] for every page: the built-in three and each
    settings_pages module with a PAGE. A module that fails to import is
    reported on stderr and left out -- one broken page must not take the
    window with it."""
    found = [(m, lambda k=m["id"]: DisplayPage(k)) for m in BUILTIN]
    for info in pkgutil.iter_modules(settings_pages.__path__):
        if info.name.startswith("_") or info.name == "common":
            continue
        try:
            mod = importlib.import_module(f"settings_pages.{info.name}")
        except Exception as exc:
            print(f"settings: page {info.name} failed to load: {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        if isinstance(getattr(mod, "PAGE", None), dict) and hasattr(mod, "Page"):
            found.append((mod.PAGE, mod.Page))
    found.sort(key=lambda p: _catalog.sort_key(p[0]))
    return found


def printable(event):
    """The character a key press types, or "" (Ctrl / Alt chords, arrows,
    and the space bar, which presses the focused button)."""
    if event.state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.MOD1_MASK | Gdk.ModifierType.SUPER_MASK):
        return ""
    char = chr(Gdk.keyval_to_unicode(event.keyval) or 0)
    return char if char.isprintable() and not char.isspace() and char != "\0" else ""


# -- the window's content: sidebar (search, pages by group) and the pages -----------------
class SettingsView(Gtk.Box):
    """Everything inside the window, as a box, so --render-window can draw it
    offscreen the same way the window shows it."""

    def __init__(self):
        super().__init__(spacing=0)
        self.set_name("panel")

        side_outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        side_outer.set_margin_end(12)
        side_outer.set_size_request(250, -1)     # the same width while it shows only the matches
        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text("Search settings")
        self.search.set_width_chars(18)
        self.search.connect("search-changed", lambda _e: self.filter())
        self.search.connect("activate", lambda _e: self.open_first())
        self.search.connect("stop-search", lambda _e: self.search.set_text(""))
        side_outer.pack_start(self.search, False, False, 0)
        # Under the box while searching: what Enter opens, or that nothing matched.
        self.search_note = dp.label("", "ctl-sub")
        self.search_note.set_line_wrap(True)
        self.search_note.set_max_width_chars(22)
        self.search_note.set_no_show_all(True)
        side_outer.pack_start(self.search_note, False, False, 0)

        # Two lists in the one scroll: the normal sidebar by group, and the
        # matches of a search (their own buttons, best first), only one shown.
        side_scroll = Gtk.ScrolledWindow()
        side_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        lists = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        self.results = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        self.results.set_no_show_all(True)
        lists.pack_start(self.side, False, False, 0)
        lists.pack_start(self.results, False, False, 0)
        side_scroll.add(lists)
        side_outer.pack_start(side_scroll, True, True, 0)
        self.pack_start(side_outer, False, False, 0)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(120)
        self.pack_start(self.stack, True, True, 0)

        self.buttons, self.pages, self.metas = {}, {}, []
        self.current, self.first_match = None, None
        group = None
        for meta, factory in discover():
            try:
                page = factory()
            except Exception as exc:
                print(f"settings: page {meta['id']} failed to build: {type(exc).__name__}: {exc}", file=sys.stderr)
                continue
            if meta.get("group") != group:
                group = meta.get("group")
                self.side.pack_start(dp.label((group or "").upper(), "kb-heading"), False, False, 0)
            b = Gtk.Button(label=f"{meta.get('icon', '')}   {meta['title']}")
            b.get_style_context().add_class("dev-pick")
            b.get_child().set_xalign(0)
            b.connect("clicked", lambda _b, k=meta["id"]: self.show(k))
            self.side.pack_start(b, False, False, 0)
            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroll.add(page.widget)
            self.stack.add_named(scroll, meta["id"])
            self.buttons[meta["id"]], self.pages[meta["id"]] = b, page
            self.metas.append(meta)

    # -- search ------------------------------------------------------------------------
    def result_button(self, meta, why):
        """A match in the search list: the page, and under it the keyword
        that found it when the title does not say it."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        title = Gtk.Label(label=f"{meta.get('icon', '')}   {meta['title']}")
        title.set_xalign(0)
        box.pack_start(title, False, False, 0)
        if why:
            sub = dp.label(why, "ctl-sub")
            sub.set_margin_start(28)        # under the title, past the icon
            box.pack_start(sub, False, False, 0)
        b = Gtk.Button()
        b.add(box)
        b.get_style_context().add_class("dev-pick")
        if meta["id"] == self.current:
            b.get_style_context().add_class("active")
        b.connect("clicked", lambda _b, k=meta["id"]: self.show(k))
        return b

    def filter(self):
        """Redraw the sidebar for what is in the search box: the groups when
        it is empty, the matching pages (best first) when not."""
        query = self.search.get_text().strip()
        common.clear(self.results)
        if not query:
            self.first_match = None
            self.results.hide()
            self.search_note.hide()
            self.side.show()
            return
        found = _catalog.search(self.metas, query)
        self.first_match = found[0]["id"] if found else None
        for meta in found:
            self.results.pack_start(self.result_button(meta, _catalog.hint(meta, query)), False, False, 0)
        self.search_note.set_text(f"Enter opens {found[0]['title']}" if found
                                  else f"No page matches “{query}”")
        self.side.hide()
        self.results.show()     # show_all() skips a no-show-all widget itself
        for child in self.results.get_children():
            child.show_all()
        self.search_note.show()

    def open_first(self):
        if self.first_match:
            self.show(self.first_match)

    def search_for(self, words):
        """Put words in the search box and open the best page they find; the
        other matches stay listed. False when nothing matches."""
        self.search.set_text(words)
        self.filter()
        self.open_first()
        return self.first_match is not None

    # -- pages -------------------------------------------------------------------------
    def show(self, key):
        if key not in self.buttons:
            key = next(iter(self.buttons))
        self.current = key
        self.stack.set_visible_child_name(key)
        for k, b in self.buttons.items():
            (b.get_style_context().add_class if k == key else b.get_style_context().remove_class)("active")
        if self.search.get_text().strip():
            self.filter()           # the matches' "active" mark follows too
        try:
            self.pages[key].refresh()
        except Exception as exc:
            print(f"settings: page {key} failed to refresh: {type(exc).__name__}: {exc}", file=sys.stderr)
        try:
            os.makedirs(os.path.dirname(STATE), exist_ok=True)
            with open(STATE, "w") as handle:
                handle.write(key)
        except OSError:
            pass

    def open(self, arg):
        """`settings.py <arg>`: a page id opens that page; other words go to
        the search. Returns a line to say on the command line, or ""."""
        if not arg:
            return ""
        if arg in self.buttons:
            self.search.set_text("")
            self.show(arg)
            return ""
        if self.search_for(arg):
            return ""
        return f"settings: no page matches {arg!r} (settings.py --list shows them)"


# -- the window ------------------------------------------------------------------------------
class Settings(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Settings")
        self.set_default_size(1000, 800)
        self.set_name("panel-window")
        self.connect("key-press-event", self.on_key)
        self.view = SettingsView()
        self.add(self.view)
        self.show_all()
        self.view.show(self.last_page())
        self.view.search.grab_focus()

    def on_key(self, _w, event):
        search = self.view.search
        # A page's popover is open (Keyboard shortcuts' "press the new keys",
        # a menu): its keys are its own -- Esc closes it, not the window, and
        # a letter is the shortcut being recorded, not a search. A modal
        # popover holds GTK's grab while it is up.
        if isinstance(Gtk.grab_get_current(), Gtk.Popover):
            return False
        if event.keyval == Gdk.KEY_Escape:
            if search.get_text():
                search.set_text("")
                search.grab_focus()
            else:
                self.close()
            return True
        if event.keyval == Gdk.KEY_f and event.state & Gdk.ModifierType.CONTROL_MASK:
            search.grab_focus()
            return True
        # Typing with the focus on a button, a switch or a slider (anything
        # that does not take text) goes to the search box.
        if not isinstance(self.get_focus(), (Gtk.Editable, Gtk.TextView)) and printable(event):
            search.grab_focus_without_selecting()
            search.event(event)
            return True
        return False

    @staticmethod
    def last_page():
        try:
            with open(STATE) as handle:
                return handle.read().strip()
        except OSError:
            return "screens"


def pump(seconds):
    end = GLib.get_monotonic_time() + int(seconds * 1e6)
    while GLib.get_monotonic_time() < end:
        Gtk.main_iteration_do(False)
        if not Gtk.events_pending():
            GLib.usleep(20000)


def render(page_id, out, seconds=4.0):
    """settings.py --render <page> <out.png> [seconds]: build one page in an
    offscreen window, let its refresh (and background work) run for
    `seconds`, save a PNG. For checking a page without putting anything on
    the screens; exit 1 if the page is unknown or failed."""
    panelui.load_css()
    pages = dict((m["id"], f) for m, f in discover())
    if page_id not in pages:
        sys.exit(f"settings: no page {page_id!r} (have: {', '.join(pages)})")
    page = pages[page_id]()
    win = Gtk.OffscreenWindow()
    win.set_name("panel-window")
    box = Gtk.Box()
    box.set_name("panel")
    box.set_size_request(820, -1)
    box.pack_start(page.widget, True, True, 0)
    win.add(box)
    win.show_all()
    page.refresh()
    pump(seconds)
    win.get_pixbuf().savev(out, "png", [], [])
    print(out)


def render_window(out, seconds=3.0, words=""):
    """settings.py --render-window <out.png> [seconds] [words]: the whole
    window's content offscreen (1000 x 800), on the Screens page or, with
    words, as the search box shows them. Writes no last-page state."""
    global STATE
    STATE = os.devnull
    panelui.load_css()
    win = Gtk.OffscreenWindow()
    win.set_name("panel-window")
    view = SettingsView()
    view.set_size_request(1000, 800)
    win.add(view)
    win.show_all()
    if not (words and view.search_for(words)):
        view.show("screens")
    pump(seconds)
    win.get_pixbuf().savev(out, "png", [], [])
    print(out)


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.window = None

    def do_command_line(self, line):
        args = line.get_arguments()[1:]
        if self.window is None:
            panelui.load_css()
            self.window = Settings(self)
        said = self.window.view.open(" ".join(args))
        if said:
            line.printerr(said + "\n")
        self.window.present()
        return 0


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "--render":
        render(sys.argv[2], sys.argv[3], float(sys.argv[4]) if len(sys.argv) > 4 else 4.0)
        sys.exit(0)
    if len(sys.argv) >= 3 and sys.argv[1] == "--render-window":
        render_window(sys.argv[2], float(sys.argv[3]) if len(sys.argv) > 3 else 3.0, " ".join(sys.argv[4:]))
        sys.exit(0)
    GLib.set_prgname(APP_ID)
    sys.exit(App().run(sys.argv))
