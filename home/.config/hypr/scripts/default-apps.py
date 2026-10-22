#!/usr/bin/env python3
"""Default apps: which installed app opens web links, mail, folders, text,
pictures, videos, music, PDFs, office files, archives and calendars -- and
which terminal and file manager the keys start. The Settings window's
"Default apps" page (settings_pages/apps.py) is a face on this script; the
search bar and the keys use the same commands.

    default-apps.py list [--json]        every role: the app it opens in now,
                                         the installed apps that can, the
                                         system's own default, whether you
                                         chose it, how many of its file types
                                         open somewhere else ("mixed")
    default-apps.py links [--json]       the same for link types (mailto:,
                                         magnet:, ssh:, steam:, ...), the
                                         ones the roles do not already cover
    default-apps.py get ROLE             the desktop id it opens in now
    default-apps.py set ROLE APP         APP is a desktop id
                                         (org.gnome.Loupe.desktop; the
                                         ".desktop" may be left off)
    default-apps.py reset ROLE           back to the system's own default
    default-apps.py run ROLE [ARG...]    start it, replacing this process:
          run terminal [--dir D] [-- CMD ARG...]
                                         the terminal, in D, running CMD
          run files [PATH]               the file manager (a new window)
          run browser [URL]              the browser
          run editor FILE...             (and the other roles) open in it
          --dry-run anywhere after `run`: print the command, start nothing

ROLE is one of: browser mail files terminal editor image video music pdf
documents spreadsheets presentations archive calendar -- or any MIME type
("image/webp", "x-scheme-handler/magnet"), which sets just that one type.

Where it is kept
----------------
Every role but the terminal is a MIME role: it is saved where every app
already looks, the freedesktop ~/.config/mimeapps.list ([Default
Applications]; the [Added Associations] list gets the app at its front too,
the way `gio mime` does it, and a [Removed Associations] entry that would
hide it is dropped). That file is what xdg-open, GTK and Qt apps, browsers'
"open downloaded file", the launcher's web tiles and this desktop's scripts
all read, so one choice here is the choice everywhere, and it survives a
Hyprland reload and a re-login because it is just a file. A role is a set of
types, not one: "browser" is x-scheme-handler/http and /https, text/html and
application/xhtml+xml always (its CORE), plus every other type of its
family the chosen app says it opens (its EXTRA -- .htm/.shtml/.xht, about:,
ftp:), so a choice never leaves .xhtml files in the previous browser.
A desktop-specific ~/.config/hyprland-mimeapps.list wins over mimeapps.list,
so a choice also takes the type out of that file if it is there.

The file manager is a MIME role as well (inode/directory): the folder
xdg-open opens is the window ALT+W opens, never two different apps.
`run browser` likewise starts the x-scheme-handler/https default (there is
no browser key yet; a bind would be exec_cmd("...default-apps.py run
browser")).

The terminal is not a MIME type. It is kept in $XDG_STATE_HOME/hypr/
default-apps.conf (terminal=<desktop id>, key=value like display.conf); the
same id also goes to ~/.config/xdg-terminals.list, the file the
xdg-terminal-exec standard reads (so GLib opens Terminal=true apps in it,
once xdg-terminal-exec is installed). Unset means the config's own choice,
COSMIC Terminal, the one ALT+Q always started.

"System default" is what GLib answers with no user mimeapps.list at all
(this script asks itself in a child process with XDG_CONFIG_HOME pointed at
an empty folder): /usr/share/applications/mimeapps.list and the apps' own
claims. Reset deletes the role's [Default Applications] lines from the user
files and moves the system's app to the front of their [Added Associations]
lists for those types (GLib would otherwise take the app `set` put there).

Starting an app (`run`)
-----------------------
The desktop entry's Exec= line with its field codes filled in (%u/%U a URI,
%f/%F a path, %i/%c/%k as the spec says), then exec -- no shell, and the app
replaces this process, so the bind's exec_cmd starts the app itself the way
it did before. Terminal=true apps (vim, htop) run inside the chosen
terminal. If anything at all goes wrong, `run terminal` and `run files` fall
back to the commands the binds used to run (cosmic-term, nautilus
--new-window), so ALT+Q and ALT+W never become dead keys.

Test seams: XDG_CONFIG_HOME, XDG_DATA_HOME/XDG_DATA_DIRS (GLib's own) and
XDG_STATE_HOME pick every file this reads or writes.
"""
import json
import os
import shlex
import subprocess
import sys
import tempfile
import urllib.parse

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio  # noqa: E402

try:                                   # GLib 2.86+: DesktopAppInfo moved to GioUnix
    gi.require_version("GioUnix", "2.0")
    from gi.repository import GioUnix  # noqa: E402
    DesktopAppInfo = GioUnix.DesktopAppInfo
except (ValueError, ImportError):
    DesktopAppInfo = Gio.DesktopAppInfo


def config_home():
    return os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")


def data_home():
    return os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")


def state_file():
    return os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                        "hypr", "default-apps.conf")


def user_mimeapps():
    """The user-level mimeapps.list files, in the order GLib reads them:
    the desktop-specific one wins, then ~/.config/mimeapps.list (the one we
    write), then the deprecated ~/.local/share/applications/mimeapps.list."""
    desktops = [d.lower() for d in (os.environ.get("XDG_CURRENT_DESKTOP") or "").split(":") if d]
    out = [os.path.join(config_home(), f"{d}-mimeapps.list") for d in desktops]
    return out + [os.path.join(config_home(), "mimeapps.list"),
                  os.path.join(data_home(), "applications", "mimeapps.list")]


MAIN_LIST = lambda: os.path.join(config_home(), "mimeapps.list")  # noqa: E731
TERMINALS_LIST = lambda: os.path.join(config_home(), "xdg-terminals.list")  # noqa: E731
DEFAULTS, ADDED, REMOVED = "Default Applications", "Added Associations", "Removed Associations"


# -- the roles -----------------------------------------------------------------
class Role:
    """A kind of app. core: the types that define it, always set together;
    extra: more of its types, set only when the chosen app claims them --
    a full type, or "image/*" for the whole family. category: a desktop
    Categories= value that also makes an app a candidate (a browser that
    claims no MIME types at all, Orion's flatpak, is still a browser).
    strict: only apps with that category are offered -- VSCodium and Disk
    Usage Analyzer claim folders, Chrome claims PNGs, but neither is a file
    manager; the category is what says "I am one". pref: not a MIME role
    (the terminal, kept in the state file)."""

    def __init__(self, rid, title, group, glyph, core=(), extra=(), category=None, strict=False, pref=False,
                 what=""):
        self.id, self.title, self.group, self.glyph = rid, title, group, glyph
        self.core, self.extra, self.category, self.pref, self.what = list(core), list(extra), category, pref, what
        self.strict = strict

    @property
    def primary(self):
        return self.core[0] if self.core else None


ARCHIVES = ["application/x-tar", "application/x-compressed-tar", "application/x-bzip2-compressed-tar",
            "application/x-xz-compressed-tar", "application/x-zstd-compressed-tar", "application/x-lzma-compressed-tar",
            "application/x-7z-compressed", "application/x-rar", "application/vnd.rar", "application/x-rar-compressed",
            "application/gzip", "application/x-gzip", "application/x-bzip2", "application/x-bzip", "application/x-xz",
            "application/zstd", "application/x-zstd", "application/x-lzma", "application/x-lz4", "application/x-lzip",
            "application/x-cpio", "application/x-archive", "application/x-arj", "application/x-lha",
            "application/vnd.ms-cab-compressed", "application/x-cd-image", "application/x-iso9660-image",
            "application/x-zip-compressed", "application/x-java-archive", "application/x-compress",
            "application/x-ace", "application/x-squashfs"]

ROLES = [
    Role("browser", "Web browser", "web", "",
         core=["x-scheme-handler/https", "x-scheme-handler/http", "text/html", "application/xhtml+xml"],
         extra=["application/x-extension-htm", "application/x-extension-html", "application/x-extension-shtml",
                "application/x-extension-xhtml", "application/x-extension-xht", "application/xhtml_xml",
                "x-scheme-handler/about", "x-scheme-handler/unknown", "x-scheme-handler/ftp",
                "application/x-mimearchive"],
         category="WebBrowser", strict=True, what="web links, .html files"),
    Role("mail", "Mail", "web", "",
         core=["x-scheme-handler/mailto"],
         extra=["message/rfc822", "application/mbox", "application/x-extension-eml", "x-scheme-handler/mid",
                "message/*"],
         category="Email", strict=True, what="mailto: links, .eml messages"),
    Role("calendar", "Calendar", "web", "",
         core=["text/calendar"],
         extra=["x-scheme-handler/webcal", "x-scheme-handler/webcals", "application/ics", "text/x-vcalendar"],
         category="Calendar", what="invitations (.ics), webcal: subscriptions"),
    Role("files", "File manager", "system", "",
         core=["inode/directory"], extra=["application/x-gnome-saved-search"],
         category="FileManager", strict=True, what="folders, and the ALT+W key"),
    Role("terminal", "Terminal", "system", "", category="TerminalEmulator", pref=True,
         what="the ALT+Q key, and apps that run in a terminal"),
    Role("image", "Image viewer", "media", "",
         core=["image/png", "image/jpeg"], extra=["image/*"], what="pictures"),
    Role("video", "Video player", "media", "",
         core=["video/mp4", "video/x-matroska", "video/webm"],
         extra=["video/*", "application/x-matroska", "application/vnd.rn-realmedia", "application/x-flash-video"],
         what="videos"),
    Role("music", "Music player", "media", "",
         core=["audio/mpeg", "audio/flac"], extra=["audio/*", "application/ogg", "application/x-ogg"],
         what="music and sound files"),
    Role("editor", "Text editor", "documents", "",
         core=["text/plain"],
         extra=["text/*", "application/x-shellscript", "application/json", "application/xml", "application/x-yaml",
                "application/yaml", "application/toml", "application/javascript", "application/x-desktop",
                "application/x-php", "application/x-perl", "application/x-ruby", "application/sql",
                "application/x-trash", "application/x-subrip"],
         category="TextEditor", what="text, code and config files"),
    Role("pdf", "PDF viewer", "documents", "",
         core=["application/pdf"], extra=["application/x-pdf", "application/x-bzpdf", "application/x-gzpdf",
                                          "application/x-xzpdf"], what="PDF documents"),
    Role("documents", "Word processor", "documents", "",
         core=["application/vnd.openxmlformats-officedocument.wordprocessingml.document",
               "application/vnd.oasis.opendocument.text"],
         extra=["application/msword", "application/rtf", "text/rtf",
                "application/vnd.oasis.opendocument.text-template",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.template",
                "application/vnd.ms-word.document.macroEnabled.12", "application/vnd.wordperfect"],
         what=".docx, .odt, .doc, .rtf"),
    Role("spreadsheets", "Spreadsheets", "documents", "",
         core=["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
               "application/vnd.oasis.opendocument.spreadsheet"],
         extra=["application/vnd.ms-excel", "application/vnd.ms-excel.sheet.macroEnabled.12",
                "application/vnd.oasis.opendocument.spreadsheet-template",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.template", "text/csv",
                "text/tab-separated-values"],
         what=".xlsx, .ods, .xls, .csv"),
    Role("presentations", "Presentations", "documents", "",
         core=["application/vnd.openxmlformats-officedocument.presentationml.presentation",
               "application/vnd.oasis.opendocument.presentation"],
         extra=["application/vnd.ms-powerpoint", "application/vnd.oasis.opendocument.presentation-template",
                "application/vnd.openxmlformats-officedocument.presentationml.slideshow",
                "application/vnd.openxmlformats-officedocument.presentationml.template"],
         what=".pptx, .odp, .ppt"),
    Role("archive", "Archive manager", "documents", "",
         core=["application/zip"], extra=ARCHIVES, category="Archiving", what=".zip, .tar.gz, .7z, .rar"),
]
BY_ID = {r.id: r for r in ROLES}
GROUP_TITLES = {"web": "WEB, MAIL AND CALENDAR", "system": "FILES AND TERMINAL", "media": "PICTURES, VIDEO, MUSIC",
                "documents": "DOCUMENTS"}

# The terminal ALT+Q started before this script existed: the default when
# nothing is chosen, and the fallback when something goes wrong.
TERMINAL_DEFAULT = "com.system76.CosmicTerm.desktop"
FALLBACK = {"terminal": ["cosmic-term"], "files": ["nautilus", "--new-window"]}

# How each terminal takes a working directory and a command (by its
# executable's name). `run terminal` also chdir()s to the directory first,
# so a terminal not listed here still opens there; a command for an unlisted
# one goes after -e, the xterm convention nearly all of them follow.
# cosmic-term's -e is its xdg-terminal-exec compatibility flag; its --help
# lists only -w.
TERMINAL_ARGS = {
    "kitty": {"dir": ["--directory", "{}"], "cmd": []},
    "ptyxis": {"new": ["--new-window"], "dir": ["-d", "{}"], "cmd": ["--"]},
    "cosmic-term": {"dir": ["-w", "{}"], "cmd": ["-e"]},
    "gnome-terminal": {"dir": ["--working-directory={}"], "cmd": ["--"]},
    "kgx": {"dir": ["--working-directory={}"], "cmd": ["--"]},
    "konsole": {"dir": ["--workdir", "{}"], "cmd": ["-e"]},
    "foot": {"dir": ["--working-directory={}"], "cmd": []},
    "footclient": {"dir": ["--working-directory={}"], "cmd": []},
    "alacritty": {"dir": ["--working-directory", "{}"], "cmd": ["-e"]},
    "wezterm": {"new": ["start"], "dir": ["--cwd", "{}"], "cmd": ["--"]},
    "ghostty": {"dir": ["--working-directory={}"], "cmd": ["-e"]},
    "xfce4-terminal": {"dir": ["--working-directory={}"], "cmd": ["-x"]},
    "tilix": {"dir": ["--working-directory={}"], "cmd": ["-e"]},
    "xterm": {"dir": [], "cmd": ["-e"]},
}

# Link types worth a name of their own on the page; the rest show their
# scheme. Schemes that are an app's private plumbing (sign-in callbacks)
# are left out entirely.
LINK_TITLES = {
    "x-scheme-handler/tel": "Phone numbers (tel:)", "x-scheme-handler/sms": "Text messages (sms:)",
    "x-scheme-handler/geo": "Places (geo:)", "x-scheme-handler/maps": "Maps (maps:)",
    "x-scheme-handler/magnet": "Torrents (magnet:)", "x-scheme-handler/ssh": "SSH (ssh:)",
    "x-scheme-handler/rdp": "Remote desktop (rdp:)", "x-scheme-handler/vnc": "Remote desktop (vnc:)",
    "x-scheme-handler/spice": "Virtual machines (spice:)", "x-scheme-handler/steam": "Steam (steam:)",
    "x-scheme-handler/matrix": "Matrix chat (matrix:)", "x-scheme-handler/irc": "IRC (irc:)",
    "x-scheme-handler/appstream": "App store (appstream:)", "x-scheme-handler/help": "Help pages (help:)",
    "x-scheme-handler/man": "Manual pages (man:)", "x-scheme-handler/discord": "Discord (discord:)",
    "x-scheme-handler/zoommtg": "Zoom meetings (zoommtg:)", "x-scheme-handler/msteams": "Teams (msteams:)",
    "x-scheme-handler/slack": "Slack (slack:)", "x-scheme-handler/tg": "Telegram (tg:)",
    "x-scheme-handler/spotify": "Spotify (spotify:)", "x-scheme-handler/feed": "News feeds (feed:)",
    "x-scheme-handler/sftp": "SFTP (sftp:)", "x-scheme-handler/smb": "Network shares (smb:)",
    "x-scheme-handler/rtsp": "Video streams (rtsp:)", "x-scheme-handler/telnet": "Telnet (telnet:)",
}
LINK_HIDE = ("oauth", "googleusercontent", "anaconda-", "systemsettings", "x-scheme-handler/extlink")


def is_link_hidden(mime):
    return any(word in mime for word in LINK_HIDE)


# -- which role a MIME type belongs to ---------------------------------------
def matches(pattern, mime):
    return mime == pattern or (pattern.endswith("/*") and mime.startswith(pattern[:-1]))


def owner(mime):
    """The role a type belongs to, or None. An exact entry anywhere (any
    role's core or extra) beats a family wildcard, so text/html is the
    browser's and text/calendar the calendar's even though the editor takes
    "text/*"; among wildcards the first role in ROLES wins."""
    for role in ROLES:
        if mime in role.core or mime in role.extra:
            return role
    for role in ROLES:
        if any(matches(p, mime) for p in role.extra if p.endswith("/*")):
            return role
    return None


def owns(role, mime):
    return owner(mime) is role


def role_types(role, claimed):
    """The types `set` gives the chosen app: the core always, plus each
    type the app claims (`claimed`, its MimeType= list) that is this role's."""
    out = list(role.core)
    for mime in claimed:
        if mime not in out and owns(role, mime) and any(matches(p, mime) for p in role.extra):
            out.append(mime)
    return out


# -- mimeapps.list, edited in place --------------------------------------------
class MimeApps:
    """A mimeapps.list kept line for line: comments, other groups and keys
    we do not touch stay exactly as they were. Values are desktop-id lists
    ("a.desktop;b.desktop;")."""

    def __init__(self, path):
        self.path = path
        self.groups = []                     # [[name or None, [lines]]]
        try:
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
        except OSError:
            text = ""
        current = [None, []]
        self.groups.append(current)
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                current = [stripped[1:-1], []]
                self.groups.append(current)
            else:
                current[1].append(line)

    def _group(self, name, create=False):
        for group in self.groups:
            if group[0] == name:
                return group
        if create:
            group = [name, []]
            self.groups.append(group)
            return group
        return None

    @staticmethod
    def _key(line):
        if "=" not in line or line.lstrip().startswith("#"):
            return None
        return line.split("=", 1)[0].strip()

    def get(self, group_name, key):
        group = self._group(group_name)
        for line in (group[1] if group else []):
            if self._key(line) == key:
                return [v.strip() for v in line.split("=", 1)[1].split(";") if v.strip()]
        return []

    def keys(self, group_name):
        group = self._group(group_name)
        return [k for k in (self._key(line) for line in (group[1] if group else [])) if k]

    def put(self, group_name, key, values, trailing=True):
        """Set key to the list `values`; an empty list deletes the key."""
        group = self._group(group_name, create=bool(values))
        if group is None:
            return
        text = ";".join(values) + (";" if trailing else "")
        lines, done = [], False
        for line in group[1]:
            if self._key(line) == key:
                if values and not done:
                    lines.append(f"{key}={text}")
                done = True
                continue
            lines.append(line)
        if values and not done:
            # after the group's last key, before any blank lines at its end
            at = len(lines)
            while at and not lines[at - 1].strip():
                at -= 1
            lines.insert(at, f"{key}={text}")
        group[1] = lines

    def text(self):
        out = []
        for name, lines in self.groups:
            if name is None and not any(line.strip() for line in lines):
                continue
            if name is not None:
                if out and out[-1].strip():
                    out.append("")
                out.append(f"[{name}]")
            out.extend(lines)
        while out and not out[-1].strip():
            out.pop()
        return "\n".join(out) + "\n"

    def save(self):
        folder = os.path.dirname(self.path)
        os.makedirs(folder, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=folder, prefix=".mimeapps-")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(self.text())
        try:
            os.chmod(tmp, os.stat(self.path).st_mode & 0o777)
        except OSError:
            os.chmod(tmp, 0o644)
        os.replace(tmp, self.path)


def assign(mime_list, types, app_id):
    """Make app_id the default for each of `types` in a MimeApps -- the
    [Default Applications] line, the front of [Added Associations], and out
    of [Removed Associations] -- the way g_app_info_set_as_default_for_type
    does it."""
    for mime in types:
        mime_list.put(DEFAULTS, mime, [app_id], trailing=False)
        added = [a for a in mime_list.get(ADDED, mime) if a != app_id]
        mime_list.put(ADDED, mime, [app_id] + added)
        removed = mime_list.get(REMOVED, mime)
        if app_id in removed:
            mime_list.put(REMOVED, mime, [a for a in removed if a != app_id])


def unassign(mime_list, types):
    """Drop the [Default Applications] lines for `types`: what is left is
    the system's own default. Added associations stay (they only make an
    app show up in "Open with")."""
    changed = False
    for mime in types:
        if mime_list.get(DEFAULTS, mime):
            mime_list.put(DEFAULTS, mime, [])
            changed = True
    return changed


# -- the installed apps ----------------------------------------------------------
def norm_id(app):
    return app if app.endswith(".desktop") else app + ".desktop"


def lookup(app_id):
    try:
        return DesktopAppInfo.new(norm_id(app_id))
    except TypeError:
        return None


def is_flatpak(info):
    return "/flatpak/exports/" in (info.get_filename() or "")


def describe(info):
    if info is None:
        return None
    icon = info.get_icon()
    return {"id": info.get_id(), "name": info.get_display_name() or info.get_name() or info.get_id(),
            "icon": icon.to_string() if icon else "", "flatpak": is_flatpak(info),
            "hidden": not info.should_show()}


def categories(info):
    return [c for c in (info.get_categories() or "").split(";") if c]


def default_for(mime):
    info = Gio.AppInfo.get_default_for_type(mime, False)
    return info.get_id() if info else None


def candidates(role, apps, current=None):
    """The installed apps that can be this role: they claim one of its core
    types (or, for a link, the scheme), or carry its category, plus apps
    the user added for it and the one it opens in now. Apps hidden from menus
    (NoDisplay) are offered only when they claim a core type themselves
    and no shown app has the same name -- Okular registers PDFs through a
    hidden okularApplication_pdf, but a hidden URL helper of a shown editor
    is no editor."""
    picked, seen = [], set()
    core = set(role.core)

    def add(info, via_mime):
        if not info or info.get_id() in seen:
            return
        if role.strict and role.category not in categories(info) and info.get_id() != current:
            return
        if not info.should_show() and not via_mime and info.get_id() != current:
            return
        seen.add(info.get_id())
        picked.append(info)

    if role.primary:
        for info in Gio.AppInfo.get_recommended_for_type(role.primary):
            add(info, True)
    for info in apps:
        claimed = set(info.get_supported_types() or [])
        if claimed & core:
            add(info, True)
        elif role.category and role.category in categories(info):
            add(info, False)
    if current:
        add(lookup(current), True)
    shown = {(i.get_display_name() or "").lower() for i in picked if i.should_show()}
    out = [i for i in picked if i.should_show() or i.get_id() == current
           or (i.get_display_name() or "").lower() not in shown]
    return sorted(out, key=lambda i: (i.get_id() != current, (i.get_display_name() or "").lower()))


def system_defaults(types):
    """{type: desktop id or None} as GLib sees it without the user's
    mimeapps.list files: a child process with XDG_CONFIG_HOME on an empty
    folder. (The child still reads the deprecated
    ~/.local/share/applications/mimeapps.list: hiding it would hide the
    user's own desktop entries with it, and it is empty or obsolete on any
    current system.)"""
    with tempfile.TemporaryDirectory(prefix="default-apps-") as empty:
        env = dict(os.environ, XDG_CONFIG_HOME=empty)
        try:
            out = subprocess.run([sys.executable, os.path.abspath(__file__), "_defaults", *types],
                                 capture_output=True, text=True, timeout=20, env=env).stdout
            return json.loads(out or "{}")
        except (OSError, subprocess.SubprocessError, ValueError):
            return {}


def user_set(types):
    """True when a user mimeapps.list names a default for any of `types`."""
    for path in user_mimeapps():
        if os.path.exists(path):
            m = MimeApps(path)
            if any(m.get(DEFAULTS, t) for t in types):
                return True
    return False


# -- the terminal ----------------------------------------------------------------
def read_state():
    out = {}
    try:
        with open(state_file()) as handle:
            for line in handle:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    out[key.strip()] = value.strip()
    except OSError:
        pass
    return out


def write_state(values):
    path = state_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as handle:
        handle.write("# default-apps.py: the choices that are not MIME types (the rest live in "
                     "~/.config/mimeapps.list)\n")
        for key, value in sorted(values.items()):
            handle.write(f"{key}={value}\n")
    os.replace(tmp, path)


TERMINALS_MARK = "# written by ~/.config/hypr/scripts/default-apps.py"


def write_terminals_list(app_id):
    """~/.config/xdg-terminals.list (the xdg-terminal-exec spec): our
    choice first. A list the user wrote by hand (no mark) is left alone."""
    path = TERMINALS_LIST()
    try:
        with open(path) as handle:
            if TERMINALS_MARK not in handle.read():
                return
    except OSError:
        pass
    if app_id is None:
        try:
            os.remove(path)
        except OSError:
            pass
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w") as handle:
        handle.write(f"{TERMINALS_MARK}\n{app_id}\n")
    os.replace(path + ".tmp", path)


def terminal_system():
    """The terminal when nothing is chosen: COSMIC Terminal if installed,
    else the first installed terminal by name."""
    if lookup(TERMINAL_DEFAULT):
        return TERMINAL_DEFAULT
    terms = sorted((i for i in Gio.AppInfo.get_all() if "TerminalEmulator" in categories(i) and i.should_show()),
                   key=lambda i: (i.get_display_name() or "").lower())
    return terms[0].get_id() if terms else None


def terminal_current():
    chosen = read_state().get("terminal")
    if chosen and lookup(chosen):
        return chosen
    return terminal_system()


# -- get / set / reset -------------------------------------------------------------
def resolve(role_name):
    """A Role, or a one-type Role for a raw MIME type."""
    if role_name in BY_ID:
        return BY_ID[role_name]
    if "/" in role_name:
        return Role(role_name, role_name, "link", "", core=[role_name])
    sys.exit(f"default-apps.py: no role {role_name!r} (have: {' '.join(BY_ID)}, or a MIME type)")


def get(role):
    if role.pref:
        return terminal_current()
    return default_for(role.primary)


def set_default(role, app_id):
    app_id = norm_id(app_id)
    info = lookup(app_id)
    if info is None:
        sys.exit(f"default-apps.py: no installed app {app_id!r}")
    if role.pref:
        state = read_state()
        state[role.id] = app_id
        write_state(state)
        write_terminals_list(app_id)
        return []
    types = role_types(role, info.get_supported_types() or [])
    main = MimeApps(MAIN_LIST())
    assign(main, types, app_id)
    main.save()
    # A desktop-specific list would win over the line just written.
    for path in user_mimeapps():
        if path != MAIN_LIST() and os.path.basename(path) != "mimeapps.list" and os.path.exists(path):
            other = MimeApps(path)
            if unassign(other, types):
                other.save()
    return types


def all_owned(role, mime_list):
    """Every type this role owns that a user file names a default for."""
    if role.id not in BY_ID:
        return list(role.core)
    found = list(role.core)
    for mime in mime_list.keys(DEFAULTS):
        if mime not in found and owns(role, mime):
            found.append(mime)
    return found


def reset(role):
    """Back to what the page calls the system default. Deleting the role's
    [Default Applications] lines is not quite enough on its own: with no
    default line GLib takes the first app of the user's [Added
    Associations] before the system's own pick (unless a system
    mimeapps.list names a default), and `set` put the chosen app at the
    front there -- so Reset would leave the last choice in place while
    calling it "the system default". So the system's app is moved to the
    front of those lists too (nothing is deleted from them: they are also
    the "Open with" lists, and the user's own entries stay)."""
    if role.pref:
        state = read_state()
        state.pop(role.id, None)
        write_state(state)
        write_terminals_list(None)
        return
    types = list(role.core)
    for path in user_mimeapps():
        if os.path.exists(path):
            m = MimeApps(path)
            owned = all_owned(role, m)
            types += [t for t in owned if t not in types]
            if unassign(m, owned):
                m.save()
    system = system_defaults(types)
    for path in user_mimeapps():
        if os.path.exists(path):
            m = MimeApps(path)
            if put_first(m, system):
                m.save()


def put_first(mime_list, wanted):
    """For each {type: desktop id} in `wanted`, move that app to the front of
    the type's [Added Associations] list if the list has another app first.
    True when something changed."""
    changed = False
    for mime, app_id in wanted.items():
        added = mime_list.get(ADDED, mime)
        if app_id and added and added[0] != app_id:
            mime_list.put(ADDED, mime, [app_id] + [a for a in added if a != app_id])
            changed = True
    return changed


# -- list -------------------------------------------------------------------------------
def mixed(role, current_info):
    """The role's types (for its current app) that open somewhere else."""
    if current_info is None:
        return []
    return [t for t in role_types(role, current_info.get_supported_types() or [])
            if default_for(t) not in (current_info.get_id(), None)]


def list_roles():
    apps = Gio.AppInfo.get_all()
    system = system_defaults([r.primary for r in ROLES if r.primary])
    out = []
    for role in ROLES:
        current = get(role)
        info = lookup(current) if current else None
        if role.pref:
            sys_id, chosen = terminal_system(), "terminal" in read_state()
            mix = []
        else:
            sys_id = system.get(role.primary)
            chosen = user_set(role.core)
            mix = mixed(role, info)
        out.append({"id": role.id, "title": role.title, "group": role.group, "group_title": GROUP_TITLES[role.group],
                    "glyph": role.glyph, "what": role.what, "kind": "pref" if role.pref else "mime",
                    "types": role.core, "current": describe(info), "system": describe(lookup(sys_id) if sys_id else None),
                    "user_set": chosen, "mixed": mix,
                    "candidates": [describe(i) for i in candidates(role, apps, current)]})
    return out


def link_types(apps):
    found = set()
    for info in apps:
        for mime in info.get_supported_types() or []:
            if mime.startswith("x-scheme-handler/") and owner(mime) is None and not is_link_hidden(mime):
                found.add(mime)
    return sorted(found, key=lambda m: (m not in LINK_TITLES, LINK_TITLES.get(m, m)))


def list_links():
    apps = Gio.AppInfo.get_all()
    types = link_types(apps)
    system = system_defaults(types)
    out = []
    for mime in types:
        current = default_for(mime)
        handlers, seen = [], set()
        for info in list(Gio.AppInfo.get_all_for_type(mime)) + ([lookup(current)] if current else []):
            if info and info.get_id() not in seen:
                seen.add(info.get_id())
                handlers.append(info)
        handlers.sort(key=lambda i: (i.get_id() != current, (i.get_display_name() or "").lower()))
        out.append({"id": mime, "scheme": mime.split("/", 1)[1],
                    "title": LINK_TITLES.get(mime, mime.split("/", 1)[1] + ":"), "known": mime in LINK_TITLES,
                    "current": describe(lookup(current) if current else None),
                    "system": describe(lookup(system[mime]) if system.get(mime) else None),
                    "user_set": user_set([mime]), "candidates": [describe(i) for i in handlers]})
    return out


# -- run --------------------------------------------------------------------------------
def as_uri(arg):
    if "://" in arg or arg.split(":", 1)[0] in ("mailto", "tel", "sms", "magnet", "about", "geo", "webcal"):
        return arg
    return Gio.File.new_for_commandline_arg(arg).get_uri()


def as_path(arg):
    if arg.startswith("file://"):
        return urllib.parse.unquote(urllib.parse.urlparse(arg).path)
    return os.path.abspath(os.path.expanduser(arg)) if "://" not in arg else arg


def expand_exec(exec_line, targets, name="", icon="", filename=""):
    """An Exec= line with its field codes filled in, as argv (desktop entry
    spec): %u/%f take the first target, %U/%F all of them, %i becomes
    --icon ICON, %c the name, %k the file, %% a %, the deprecated ones go.
    A line with no file code gets the targets on its end, as browsers and
    Orion's flatpak expect."""
    try:
        words = shlex.split(exec_line)
    except ValueError:
        words = exec_line.split()
    argv, used = [], False
    for word in words:
        if word in ("%u", "%U", "%f", "%F"):
            used = True
            pick = targets[:1] if word in ("%u", "%f") else targets
            argv += [as_uri(t) if word in ("%u", "%U") else as_path(t) for t in pick]
        elif word == "%i":
            argv += ["--icon", icon] if icon else []
        elif word in ("%d", "%D", "%n", "%N", "%v", "%m"):
            continue
        else:
            out, i = "", 0
            while i < len(word):
                if word[i] == "%" and i + 1 < len(word):
                    code = word[i + 1]
                    if code in "uf":
                        used = True
                        out += (as_uri(targets[0]) if code == "u" else as_path(targets[0])) if targets else ""
                    elif code == "c":
                        out += name
                    elif code == "k":
                        out += filename
                    elif code == "%":
                        out += "%"
                    i += 2
                    continue
                out += word[i]
                i += 1
            if out or not word.startswith("%"):
                argv.append(out)
    if not used:
        argv += list(targets)
    return argv


def app_argv(info, targets):
    icon = info.get_icon()
    return expand_exec(info.get_commandline() or info.get_executable() or "", list(targets),
                       info.get_display_name() or "", icon.to_string() if isinstance(icon, Gio.ThemedIcon) else "",
                       info.get_filename() or "")


def terminal_argv(info, directory=None, command=None):
    base = app_argv(info, [])
    exe = os.path.basename(base[0]) if base else ""
    table = TERMINAL_ARGS.get(exe, {"dir": [], "cmd": ["-e"]})
    argv = list(base)
    for flag in table.get("new", []):
        if flag not in argv:
            argv.append(flag)
    if directory:
        argv += [part.format(directory) for part in table["dir"]]
    if command:
        argv += table["cmd"] + list(command)
    return argv


def build_run(role, args):
    """(argv, cwd) for `run ROLE ARGS`."""
    if role.pref:
        directory, command = None, None
        if "--" in args:
            command = args[args.index("--") + 1:]
            args = args[:args.index("--")]
        if "--dir" in args and args.index("--dir") + 1 < len(args):
            directory = os.path.abspath(os.path.expanduser(args[args.index("--dir") + 1]))
        info = lookup(terminal_current() or TERMINAL_DEFAULT)
        if info is None:
            raise RuntimeError("no terminal installed")
        return terminal_argv(info, directory, command), directory
    current = get(role)
    info = lookup(current) if current else None
    if info is None:
        raise RuntimeError(f"nothing opens {role.primary}")
    argv = app_argv(info, args)
    if info.get_boolean("Terminal"):
        term = lookup(terminal_current() or TERMINAL_DEFAULT)
        if term:
            argv = terminal_argv(term, None, argv)
    return argv, None


def run(role, args, dry=False):
    try:
        argv, cwd = build_run(role, args)
    except Exception as exc:  # noqa: BLE001 -- a key must never go dead
        if role.id not in FALLBACK:
            sys.exit(f"default-apps.py: {exc}")
        print(f"default-apps.py: {exc}; using {FALLBACK[role.id][0]}", file=sys.stderr)
        argv, cwd = list(FALLBACK[role.id]), None
    if dry:
        print(json.dumps({"argv": argv, "cwd": cwd}))
        return
    if cwd and os.path.isdir(cwd):
        os.chdir(cwd)
    elif role.pref:
        os.chdir(os.path.expanduser("~"))
    try:
        os.execvp(argv[0], argv)
    except OSError as exc:
        if role.id in FALLBACK and argv != FALLBACK[role.id]:
            os.execvp(FALLBACK[role.id][0], FALLBACK[role.id])
        sys.exit(f"default-apps.py: cannot start {argv[0]}: {exc}")


# -- the command line -------------------------------------------------------------------
def print_roles(rows):
    for r in rows:
        cur = r["current"]["name"] if r["current"] else "nothing"
        note = "" if r["user_set"] else "  (system default)"
        if r.get("mixed"):
            note += f"  ({len(r['mixed'])} of its types open elsewhere)"
        others = ", ".join(c["name"] for c in r["candidates"] if not r["current"] or c["id"] != r["current"]["id"])
        print(f"{r['title']:<16} {cur}{note}" + (f"   also: {others}" if others else ""))


def main(argv):
    cmd = argv[0] if argv else "list"
    if cmd == "_defaults":                     # the child system_defaults() starts
        print(json.dumps({t: default_for(t) for t in argv[1:]}))
    elif cmd == "list":
        rows = list_roles()
        print(json.dumps(rows)) if "--json" in argv else print_roles(rows)
    elif cmd == "links":
        rows = list_links()
        print(json.dumps(rows)) if "--json" in argv else print_roles(rows)
    elif cmd == "roles":
        print(" ".join(BY_ID))
    elif cmd == "get" and len(argv) == 2:
        print(get(resolve(argv[1])) or "")
    elif cmd == "set" and len(argv) == 3:
        role = resolve(argv[1])
        types = set_default(role, argv[2])
        print(f"{role.title}: {norm_id(argv[2])}" + (f" ({len(types)} types)" if types else ""))
    elif cmd == "reset" and len(argv) == 2:
        role = resolve(argv[1])
        reset(role)
        print(f"{role.title}: back to the system default ({get(role) or 'nothing'})")
    elif cmd == "run" and len(argv) >= 2:
        head = argv[2:argv.index("--")] if "--" in argv else argv[2:]
        dry = "--dry-run" in head
        rest = [a for a in head if a != "--dry-run"] + (argv[argv.index("--"):] if "--" in argv else [])
        run(resolve(argv[1]), rest, dry)
    else:
        print(__doc__.split("\n\n", 2)[1], file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main(sys.argv[1:])
