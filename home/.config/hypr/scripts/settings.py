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

The sidebar, by group (_catalog.GROUPS order; each page says its own group and
order in its PAGE, see settings_pages/common.py). A page whose PAGE names a
"parent" is not in the sidebar but a tab of that page, under a row of tabs at
the top (its "tab" is the caption); `settings.py <id>` and the search open
a tab the same as a page:

    SMART     Smart desktop      every smart feature's switch | Presence,
                                 Gestures & gaze, Memory, Folder access
    LOOK      Theme              theme, accent, glass, video player | Ambient,
                                 Effects (the display panel's own pages)
              Wallpaper & lock screen
              Text & pointer     fonts, text size, cursor | Accessibility
              Windows            gaps, borders, blur | Layout, Picture-in-picture
              Bar & toolbox
    APPS      Default apps
              Workspaces         sessions | Contexts, Focus
              Timers & alarms
              AI & assistant     models | Voice typing, Spoken replies,
                                 Clipboard, Suggestions, Assistant, Daily brief
              Screenshots & recording
    HARDWARE  Screens            HDR, brightness, refresh, arrangement
              Network & Bluetooth, Sound
              Keyboard & mouse   | Shortcuts
              Devices            USB drives, phone | Machines
    SYSTEM    Notifications      | Emergency alerts
              Privacy, Power & lock, Storage, Users & sharing, Date & region
              Startup & automations   | Automations, Background tasks
              Updates & maintenance   | Maintenance, Health
              About

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
    by_id = {m["id"]: (m, f) for m, f in found}
    return [by_id[m["id"]] for m in _catalog.arrange([m for m, _ in found])]


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

        # buttons: the sidebar's (top pages only); pages: every page, tabs
        # too; host: page id -> the sidebar page showing it; tabbed: a
        # sidebar page with tabs -> (its inner stack, its tab chips, tabs).
        self.buttons, self.pages, self.host, self.tabbed, self.metas = {}, {}, {}, {}, []
        self.current, self.first_match = None, None
        group = None
        found = discover()
        all_metas = [m for m, _ in found]
        for meta, factory in found:
            try:
                page = factory()
            except Exception as exc:
                print(f"settings: page {meta['id']} failed to build: {type(exc).__name__}: {exc}", file=sys.stderr)
                continue
            key = meta["id"]
            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroll.add(page.widget)
            self.pages[key] = page
            self.metas.append(meta)
            parent = meta.get("parent")
            if parent in self.tabbed:                  # a tab of the page before it
                self.host[key] = parent
                self.tabbed[parent][0].add_named(scroll, key)
                continue
            if meta.get("group") != group:
                group = meta.get("group")
                self.side.pack_start(dp.label((group or "").upper(), "kb-heading"), False, False, 0)
            b = Gtk.Button(label=f"{meta.get('icon', '')}   {meta['title']}")
            b.get_style_context().add_class("dev-pick")
            b.get_child().set_xalign(0)
            b.connect("clicked", lambda _b, k=key: self.show(k))
            self.side.pack_start(b, False, False, 0)
            self.buttons[key], self.host[key] = b, key
            tabs = _catalog.tabs(all_metas, key)
            if not tabs:
                self.stack.add_named(scroll, key)
                continue
            # The tabs stay put at the top; each tab scrolls on its own.
            inner = Gtk.Stack()
            inner.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
            inner.set_transition_duration(120)
            inner.add_named(scroll, key)
            chips = dp.Chips(lambda k: self.show(k), mark=False)
            chips.widget.set_max_children_per_line(len(tabs))
            chips.widget.set_margin_bottom(6)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            box.pack_start(chips.widget, False, False, 0)
            box.pack_start(inner, True, True, 0)
            self.stack.add_named(box, key)
            self.tabbed[key] = (inner, chips, tabs)

    # -- search ------------------------------------------------------------------------
    def result_button(self, meta, why):
        """A match in the search list: the page, and under it the keyword
        that found it when the title does not say it."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        title = Gtk.Label(label=f"{meta.get('icon', '')}   {meta['title']}")
        title.set_xalign(0)
        box.pack_start(title, False, False, 0)
        host = self.host.get(meta["id"], meta["id"])
        if host != meta["id"]:
            where = f"in {self.title_of(host)}"
            why = f"{where} · {why}" if why else where
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
    def title_of(self, key):
        return next((m["title"] for m in self.metas if m["id"] == key), key)

    def show(self, key):
        """A page by id: a sidebar page, or a tab of one (its page shown on
        that tab)."""
        if key not in self.pages:
            key = next(iter(self.buttons))
        self.current = key
        host = self.host[key]
        self.stack.set_visible_child_name(host)
        if host in self.tabbed:
            inner, chips, tabs = self.tabbed[host]
            inner.set_visible_child_name(key)
            chips.set(tabs, key)
        for k, b in self.buttons.items():
            (b.get_style_context().add_class if k == host else b.get_style_context().remove_class)("active")
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
        if arg in self.pages:
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
        dp.guard_wheel(self.view)       # the wheel scrolls the page, never picks a value
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
