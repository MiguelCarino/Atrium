"""Settings page: default apps (default-apps.py).

What opens a web link, a mail address, a folder, a text file, a picture, a
video, a song, a PDF, an office file, an archive, a calendar invitation --
and which terminal ALT+Q starts. Each role is a row (what it opens now,
what the system would pick) over a row of chips, one per
installed app that can do it, with its icon; a click makes that app the
default for every type of the role at once (default-apps.py set), "Reset"
puts the system's own choice back (default-apps.py reset). "Open links in"
does the same for the other link types the installed apps register
(magnet:, ssh:, tel:, steam:...): a type with more than one app to choose
from gets a row, one that only one app can open folds away under "Other
link types (one app each)" -- named or not. A type default-apps.py has no
name for gets a readable one here (link_title). The kitty notes, the
mimeapps.list button and "Check again" sit in a Details fold under Keys.

Nothing is kept here: default-apps.py writes ~/.config/mimeapps.list (and
$XDG_STATE_HOME/hypr/default-apps.conf for the terminal) and the page
redraws from what it then reports -- which is what GLib, xdg-open and every
app see too. Listing the apps takes a few hundred ms (it asks GLib about
every desktop entry, Flatpak exports included, and starts a child for the
system defaults), so it and every change run in background().
"""
from gi.repository import Gio, GLib, Gtk  # noqa: F401

from .common import *  # noqa: F401,F403  (the shared helpers and paths)

import os  # noqa: E402
import subprocess  # noqa: E402

PAGE = {"id": "apps", "title": "Default apps", "icon": "", "group": "Apps", "order": 10,
        "keywords": ["default apps", "browser", "web browser", "mail", "email", "file manager", "files",
                     "terminal", "text editor", "image viewer", "pictures", "photos", "video player", "music",
                     "pdf", "office", "documents", "spreadsheets", "presentations", "archive", "zip",
                     "calendar", "links", "open with", "xdg-open", "mimeapps"]}
DEFAULT_APPS = os.path.join(HYPR, "default-apps.py")


def cli(*args):
    """default-apps.py ARGS: its answer line -- stdout, or what it said on
    stderr when it failed (common.run keeps only stdout, which would turn
    "no installed app 'x'" into a bare "no answer")."""
    try:
        out = subprocess.run([DEFAULT_APPS, *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"default-apps.py did not run: {exc}"
    text = (out.stdout.strip() or out.stderr.strip()).splitlines()
    return text[-1] if text else ""


def app_name(app, others=()):
    """An app's name for a chip; "(Flatpak)" when another chip has the same
    name and this one is the Flatpak."""
    name = app["name"]
    if app.get("flatpak") and sum(1 for o in others if o["name"] == app["name"]) > 1:
        name += " (Flatpak)"
    return name


# Readable names for link types default-apps.py has no title for (it shows
# those as the bare "scheme:").
EXTRA_LINK_TITLES = {
    "x-scheme-handler/remmina": "Remmina connections (remmina:)",
    "x-scheme-handler/spice+tls": "Virtual machines, encrypted (spice+tls:)",
    "x-scheme-handler/spice+unix": "Virtual machines, local (spice+unix:)",
    "x-scheme-handler/anydesk": "AnyDesk sessions (anydesk:)",
    "x-scheme-handler/webex": "Webex meetings (webex:)",
}


def link_title(lk):
    """A link type's title: default-apps.py's own, a readable one from
    EXTRA_LINK_TITLES, else "Heroic links (heroic:)" built from the scheme."""
    if lk.get("known") or not lk["id"].startswith("x-scheme-handler/"):
        return lk["title"]
    if lk["id"] in EXTRA_LINK_TITLES:
        return EXTRA_LINK_TITLES[lk["id"]]
    scheme = lk["id"].split("/", 1)[1]
    return f"{scheme.split('+')[0].capitalize()} links ({scheme}:)"


def fold_links(links):
    """(rows, folded): a link type gets a row with chips when there is a
    choice to make (more than one app), and folds away under "Other link
    types (one app each)" when only one app can open it -- the same rule
    for named and unnamed types, so the fold's label is always true."""
    links = links or []
    return ([lk for lk in links if len(lk["candidates"]) > 1],
            [lk for lk in links if len(lk["candidates"]) <= 1])


def type_name(mime):
    """"OpenDocument spreadsheet" for a type the MIME database knows, the
    bare subtype ("vnd.ms-word.document.macroEnabled.12") otherwise."""
    desc = Gio.content_type_get_description(mime) or ""
    return mime.split("/", 1)[-1] if not desc or "/" in desc else desc


def role_sub(role):
    """The line under a role's title: what it opens now and why."""
    cur, system = role.get("current"), role.get("system")
    if not cur:
        text = "nothing installed opens these" if not role["candidates"] else "not set: pick one below"
    elif role.get("user_set") and system and system["id"] != cur["id"]:
        text = f"{cur['name']}  ·  your choice (system would use {system['name']})"
    elif role.get("user_set"):
        text = f"{cur['name']}  ·  your choice"
    else:
        text = f"{cur['name']}  ·  system default"
    if role.get("what"):
        text += f"  ·  {role['what']}"
    mixed = role.get("mixed") or []
    if mixed:
        text += f"  ·  {len(mixed)} type{'s' if len(mixed) != 1 else ''} open elsewhere: pick again"
    return text


def keys_text(binds):
    """"ALT+Q terminal  ·  ALT+W files" from `hyprctl binds -j`: the keys
    that run default-apps.py, as Hyprland has them loaded right now. A bind
    made from Lua reports only a function id as its arg, so those are known
    by lua/binds.lua's description ("Apps: Terminal", "Apps: File manager")."""
    mods = {1: "SHIFT", 4: "CTRL", 8: "ALT", 64: "SUPER"}
    by_desc = {"apps: terminal": "terminal", "apps: file manager": "files"}
    out = []
    for b in binds or []:
        arg = b.get("arg", "")
        role = by_desc.get(str(b.get("description", "")).strip().lower())
        if role and "default-apps.py run" not in arg:
            arg = f"default-apps.py run {role}"
        if "default-apps.py run" not in arg:
            continue
        mask = b.get("modmask", 0)
        combo = "+".join([name for bit, name in sorted(mods.items(), key=lambda m: -m[0]) if mask & bit]
                         + [b.get("key", "?").upper()])
        out.append(f"{combo} {arg.split('default-apps.py run', 1)[1].split()[0]}")
    return "  ·  ".join(out)


class AppChips:
    """Like display_panel's Chips (a wrapping row of dev-pick buttons, the
    current one lit), with each app's own icon in front of its name."""

    def __init__(self, apps, active, on_pick, system=None):
        self.widget = Gtk.FlowBox()
        self.widget.set_selection_mode(Gtk.SelectionMode.NONE)
        self.widget.set_max_children_per_line(3)
        self.widget.set_min_children_per_line(1)
        self.widget.set_column_spacing(4)
        self.widget.set_row_spacing(4)
        self.widget.set_homogeneous(False)
        self.widget.get_style_context().add_class("dev-list")
        for app in apps:
            box = Gtk.Box(spacing=6)
            image = self.icon(app.get("icon"))
            if image is not None:
                box.pack_start(image, False, False, 0)
            caption = app_name(app, apps) + ("  ·  system default" if system and app["id"] == system else "")
            text = Gtk.Label(label=caption)
            text.set_ellipsize(3)            # Pango.EllipsizeMode.END
            text.set_max_width_chars(30)
            box.pack_start(text, False, False, 0)
            button = Gtk.Button()
            button.add(box)
            button.set_tooltip_text(app["id"])
            button.get_style_context().add_class("dev-pick")
            if app["id"] == active:
                button.get_style_context().add_class("active")
            button.set_can_focus(False)
            button.connect("clicked", lambda _b, k=app["id"]: on_pick(k))
            self.widget.add(button)

    @staticmethod
    def icon(name):
        if not name:
            return None
        try:
            image = Gtk.Image.new_from_gicon(Gio.Icon.new_for_string(name), Gtk.IconSize.MENU)
        except GLib.Error:
            return None
        image.set_pixel_size(18)
        return image


class Page:
    def __init__(self):
        self.widget = page_box()
        w = self.widget
        w.pack_start(heading("DEFAULT APPS"), False, False, 0)
        w.pack_start(dp.label("What opens links, folders and files.", "ctl-sub"), False, False, 0)
        self.status = dp.label("", "ctl-sub")
        self.status.set_line_wrap(True)
        w.pack_start(self.status, False, False, 0)
        self.roles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        w.pack_start(self.roles, False, False, 0)
        w.pack_start(sep(), False, False, 0)
        w.pack_start(heading("OPEN LINKS IN"), False, False, 0)
        w.pack_start(dp.label("Other link types (web and mail follow the rows above).", "ctl-sub"), False, False, 0)
        self.links = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        w.pack_start(self.links, False, False, 0)
        w.pack_start(sep(), False, False, 0)
        w.pack_start(heading("KEYS"), False, False, 0)
        self.keys_row, self.keys_sub = row("", "Keys that follow these choices", "")
        w.pack_start(self.keys_row, False, False, 0)
        kitty = dp.label("Always kitty (they need its options): the drop-down terminal, the launcher's Run and "
                         "chat tiles, the snapshot undo window. The Hyprland/Waybar config keys open COSMIC Text "
                         "Editor. The terminal also runs apps that need one (Terminal=true). Choices are saved "
                         "in ~/.config/mimeapps.list, the file every app reads.", "ctl-sub")
        kitty.set_line_wrap(True)
        kitty.set_max_width_chars(90)
        w.pack_start(details(kitty, links_row(
            link("Open mimeapps.list", lambda: spawn(DEFAULT_APPS, "run", "editor",
                                                     os.path.expanduser("~/.config/mimeapps.list"))),
            link("Check again", self.refresh))), False, False, 0)
        self.other_open = False
        self.busy = False

    # -- data -------------------------------------------------------------------
    def refresh(self):
        if not self.roles.get_children():
            self.roles.pack_start(dp.label("finding the installed apps…", "ctl-sub"), False, False, 0)
            self.roles.show_all()
        background(lambda: (run_json(DEFAULT_APPS, "list", "--json", timeout=30),
                            run_json(DEFAULT_APPS, "links", "--json", timeout=30),
                            run_json("hyprctl", "binds", "-j", timeout=5)), self.show)

    def change(self, *args, what=""):
        """default-apps.py set/reset ROLE [APP] in the background, then redraw."""
        if self.busy:
            return
        self.busy = True
        self.status.set_text(f"{what}…")

        def done(out):
            self.busy = False
            self.status.set_text(out or f"{what}: no answer")
            self.refresh()
        background(lambda: cli(*args), done)

    # -- drawing ------------------------------------------------------------------
    def show(self, data):
        roles, links, binds = data
        clear(self.roles)
        if not roles:
            self.roles.pack_start(dp.label("Could not list the apps", "ctl-sub"), False, False, 0)
        group = None
        for role in roles or []:
            if role["group"] != group:
                group = role["group"]
                if self.roles.get_children():
                    self.roles.pack_start(sep(), False, False, 0)
                self.roles.pack_start(heading(role["group_title"]), False, False, 0)
            self.add_choice(self.roles, role, role["glyph"])
        clear(self.links)
        known, rest = fold_links(links)
        for lk in known:
            self.add_choice(self.links, dict(lk, title=link_title(lk)), "")
        if rest:
            expander = Gtk.Expander(label=f"Other link types ({len(rest)}, one app each)")
            expander.get_style_context().add_class("ctl-sub")
            expander.set_expanded(self.other_open)
            expander.connect("notify::expanded", lambda e, _p: setattr(self, "other_open", e.get_expanded()))
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            inner.set_margin_start(12)
            for lk in rest:
                cur = lk["current"]["name"] if lk["current"] else "nothing"
                line = dp.label(f"{link_title(lk)}  ·  {cur}", "ctl-sub")
                line.set_tooltip_text(lk["current"]["id"] if lk["current"] else lk["id"])
                inner.pack_start(line, False, False, 0)
            expander.add(inner)
            self.links.pack_start(expander, False, False, 0)
        if links is not None and not links:
            self.links.pack_start(dp.label("No other link types are registered.", "ctl-sub"), False, False, 0)
        keys = keys_text(binds)
        self.keys_sub.set_text(keys or "ALT+Q terminal, ALT+W files: active after the next Hyprland reload")
        self.widget.show_all()

    def add_choice(self, box, role, glyph):
        reset = None
        if role.get("user_set"):
            reset = link("Reset", lambda r=role: self.change("reset", r["id"], what=f"{r['title']}: resetting"))
            reset.set_tooltip_text("Back to the system default" + (f" ({role['system']['name']})"
                                                                   if role.get("system") else ""))
        grid, sub = row(glyph, role["title"], role_sub(role), reset)
        if role.get("mixed"):
            sub.set_tooltip_text("Still open in another app: " + ", ".join(type_name(t) for t in role["mixed"]))
        box.pack_start(grid, False, False, 0)
        apps = role["candidates"]
        if len(apps) > 1 or (apps and not role.get("current")):
            active = role["current"]["id"] if role.get("current") else None
            system = role["system"]["id"] if role.get("system") else None
            chips = AppChips(apps, active, lambda app, r=role: self.pick(r, app), system)
            chips.widget.set_margin_start(36)
            box.pack_start(chips.widget, False, False, 0)

    def pick(self, role, app):
        if role.get("current") and role["current"]["id"] == app and not role.get("mixed"):
            return
        self.change("set", role["id"], app, what=f"{role['title']}: switching")
