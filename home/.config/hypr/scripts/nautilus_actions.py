#!/usr/bin/env python3
"""Files (Nautilus): what this desktop adds to its right-click menu and its
list view. The extension itself is ~/.local/share/nautilus-python/extensions/
atrium_files.py, a thin shell nautilus-python loads into Nautilus; every
decision it makes is made here, so the tests can ask the same questions
without a Nautilus.

The right-click items, only where they make sense for what is selected:

  Open in Terminal       one folder, or the folder's background: the terminal
                         Settings > Default apps chose (default-apps.py run
                         terminal --dir), in that folder
  Open in Text Editor    local files that read as text (textish(): text/*,
                         JSON, YAML, scripts, unknown types; not pictures,
                         videos, music, PDFs, office files, archives or
                         programs): the "Text editor" default app
  Set as Wallpaper       one picture hyprpaper shows (PNG, JPEG, WebP, JPEG
                         XL): on every connected monitor, through
                         wallpaper-slideshow.py show (it stays until the
                         slideshow's next change, like a pick in Settings >
                         Wallpaper). Where the theme's moving wallpaper
                         plays (wallpaper-motion.py, over hyprpaper's still)
                         the still is set too but not seen; the notification
                         names those monitors (under_video())
  Ask the Local Model    one picture or one text file: screen-ask.py's card
                         (a LOCAL model in LM Studio, nothing leaves the
                         machine) with the picture, or the first TEXT_BYTES
                         of the text; files folder_access.refused() calls
                         secret (keys, password stores, tokens) or system are
                         never handed over
  Copy Path              local files and folders; one per line, or, when a
                         name holds a line break, shell-quoted on one line
                         (path_text())
  Copy as URI            anything, local or not (file://, sftp://, trash://)

The two Copy items hand wl-copy the text on its stdin (action_input()), not
as an argument: Linux refuses any one argument over 128 KiB, which a select-
all of a few thousand files passes.

"Local" is a file:// URI. Files Nautilus shows through gvfs (sftp://, smb://,
trash://, recent://, mtp://) get only Copy as URI: gvfs may have a FUSE path
for some of them, but a terminal, an editor or hyprpaper opening it there is
slow at best and wrong at worst (trash:// names are not the real names).

Not here, on purpose:
  - Send to phone: kde-connect-nautilus (packages/dnf.txt) already puts
    "Send to <phone> via KDE Connect" in the same menu, the same kdeconnectd
    phone.py uses; a second item would do the same thing twice.
  - Compress / Extract: Nautilus does both itself (gnome-autoar); file-roller
    is only needed for its own window.

The Git column (list view: right-click the column headers > Git) and the
emblems: a file inside a git work tree shows Modified, Staged, Added,
Renamed, Untracked or Conflict, and a folder the strongest of what is under
it (only Untracked when everything new in it is untracked). Inside a folder
git has not been told about at all, git names only that folder ("?? new/"),
so every file and folder in it is Untracked (the EVERYTHING key, kind_for()).
Changed files get
the emblem-important emblem, untracked ones emblem-new. One `git status
--porcelain=v1 -z` per folder shown (status_argv(): --no-optional-locks, so
it never takes the index lock from under your own git), never one per file;
the answer is kept per folder until the folder, the repository's index or
the file asked about changes (cache_fresh()), and for CACHE_TTL at most. It
runs asynchronously (the extension's update_file_info_full): Nautilus draws
the folder at once and the column fills in when git answers; a git that
takes longer than GIT_TIMEOUT_MS (a huge repository) is stopped and that
folder shows no status until CACHE_TTL has passed.

    nautilus_actions.py items PATH...     the items a selection would get
                                          (types from Gio, as Nautilus has them)
    nautilus_actions.py git DIR           the Git column for DIR's files
    nautilus_actions.py wallpaper PATH    what Set as Wallpaper runs
    nautilus_actions.py ask PATH          what Ask the Local Model runs

The extension loads when Nautilus starts: after installing it, `nautilus -q`
(closes every Files window) or a new login.
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
NOTIFY = os.path.join(HERE, "notify")  # notify-send with the theme's mascot (mascot_notify.py)
DEFAULT_APPS = os.path.join(HERE, "default-apps.py")
SLIDESHOW = os.path.join(HERE, "wallpaper-slideshow.py")
SCREEN_ASK = os.path.join(HERE, "screen-ask.py")
SELF = os.path.abspath(__file__)

TEXT_BYTES = 80_000         # read of a text file for the model (screen-ask.py keeps 20 000 characters)
EDITOR_MAX = 20             # more selected files than this: no "Open in Text Editor"
GIT_TIMEOUT_MS = 2500       # a git status slower than this is stopped
CACHE_TTL = 30.0            # s: a folder's git answer is asked again after this at the latest
ATTRIBUTE = "atrium_git"    # the column's attribute name (Nautilus.Column / add_string_attribute)

# hyprpaper's formats (wallpaper-slideshow.py takes png, jpg, webp, jxl)
WALLPAPER_TYPES = {"image/png", "image/jpeg", "image/webp", "image/jxl"}
# what screen-ask.py's card shows and sends (GdkPixbuf + a data URL)
ASK_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}

# Types that are not text even though they are not image/audio/video.
NOT_TEXT_PREFIXES = ("image/", "audio/", "video/", "font/", "model/", "inode/",
                     "application/vnd.openxmlformats", "application/vnd.oasis.opendocument",
                     "application/vnd.ms-", "application/x-ms")
# ...nor a type whose name has a part that starts like one of these
# ("x-compressed-tar" -> x, compressed, tar).
NOT_TEXT_WORDS = ("zip", "compressed", "archive", "tar", "gtar", "rar", "7z", "bzip", "gzip", "xz", "zstd",
                  "lzma", "lz4", "cpio", "executable", "sharedlib", "object", "core", "image", "sqlite",
                  "package", "rpm", "pdf", "flatpak", "matroska", "ogg", "wasm", "font", "java", "dosexec")
TEXT_SUFFIXES = ("+json", "+xml", "+yaml")
TEXT_TYPES = {"application/json", "application/xml", "application/x-yaml", "application/yaml",
              "application/toml", "application/javascript", "application/x-shellscript", "application/x-desktop",
              "application/x-php", "application/x-perl", "application/x-ruby", "application/sql",
              "application/x-subrip", "application/x-trash", "application/x-zerosize",
              "application/octet-stream", "application/x-wine-extension-ini", "application/x-ipynb+json"}

# The Git column. Kinds, strongest first (a folder shows the strongest of
# what is under it).
RANK = {"conflict": 6, "modified": 5, "deleted": 4, "renamed": 3, "added": 3, "staged": 3, "untracked": 1}
LABELS = {"conflict": "Conflict", "modified": "Modified", "deleted": "Deleted", "renamed": "Renamed",
          "added": "Added", "staged": "Staged", "untracked": "Untracked"}
EMBLEMS = {"conflict": "emblem-important", "modified": "emblem-important", "deleted": "emblem-important",
           "renamed": "emblem-important", "added": "emblem-important", "staged": "emblem-important",
           "untracked": "emblem-new"}
CONFLICTS = {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}
# dir_statuses()' key for "every name here": a "/" is never part of a name.
EVERYTHING = "/"


# -- pure -------------------------------------------------------------------------------------
def entry(uri, path=None, is_dir=False, mime=""):
    """One selected file as the rules below see it. path is its local path,
    or None when the URI is not file:// (entry() drops a path that came
    with another scheme: a gvfs FUSE path is not local for these rules)."""
    scheme = uri.split(":", 1)[0].lower() if ":" in uri else ""
    return {"uri": uri, "path": path if scheme == "file" and path else None,
            "dir": bool(is_dir), "mime": mime or ""}


def is_local(item):
    return item.get("path") is not None


def textish(mime):
    """Would a text editor make sense of this type? Unknown types count as
    text (a config file without an extension is application/octet-stream
    or x-zerosize); pictures, sound, video, fonts, office files, archives,
    disk images and programs do not."""
    mime = (mime or "").lower()
    if not mime or mime.startswith("text/") or mime in TEXT_TYPES or mime.endswith(TEXT_SUFFIXES):
        return True
    if mime.startswith(NOT_TEXT_PREFIXES):
        return False
    parts = re.split(r"[-.+_]", mime.split("/", 1)[-1])
    return not any(part.startswith(word) for part in parts for word in NOT_TEXT_WORDS)


def safe_name(path):
    """wallpaper-slideshow.py `show` refuses names with a tab or a line
    break (its request file is tab-separated lines)."""
    return "\t" not in path and "\n" not in path


def file_items(items):
    """The right-click items for a selection: [(key, label, tip)], in menu
    order. items are entry() dicts; none selected, no items."""
    if not items:
        return []
    out = []
    local = all(is_local(i) for i in items)
    one = items[0] if len(items) == 1 else None
    files = local and not any(i["dir"] for i in items)
    if one and local and one["dir"]:
        out.append(("terminal", "Open in Terminal", "Open the terminal in this folder"))
    if files and len(items) <= EDITOR_MAX and all(textish(i["mime"]) for i in items):
        out.append(("editor", "Open in Text Editor", "Open in the default text editor"))
    if one and files and one["mime"] in WALLPAPER_TYPES and safe_name(one["path"]):
        out.append(("wallpaper", "Set as Wallpaper", "Show this picture on every monitor"))
    if one and files and (one["mime"] in ASK_IMAGE_TYPES or textish(one["mime"])):
        out.append(("ask", "Ask the Local Model", "Ask a local model about this file (nothing leaves the machine)"))
    if local:
        out.append(("copy-path", "Copy Path" if len(items) == 1 else "Copy Paths",
                    "Copy the full path as text"))
    out.append(("copy-uri", "Copy as URI" if len(items) == 1 else "Copy as URIs", "Copy the location as a URI"))
    return out


def background_items(folder):
    """The items for a right-click on a folder's empty space."""
    if folder is None:
        return []
    out = []
    if is_local(folder):
        out.append(("terminal", "Open in Terminal", "Open the terminal in this folder"))
        out.append(("copy-path", "Copy Path", "Copy this folder's full path as text"))
    out.append(("copy-uri", "Copy as URI", "Copy this folder's location as a URI"))
    return out


def path_text(paths):
    """What Copy Path puts on the clipboard: one path as it is (spaces and
    any script as they are, no quotes); several, one per line -- unless a
    name holds a line break, where lines would split it: then every path
    shell-quoted on one line, the one form that still says where each ends."""
    paths = list(paths)
    if len(paths) == 1:
        return paths[0]
    if any("\n" in p or "\r" in p for p in paths):
        return " ".join(shlex.quote(p) for p in paths)
    return "\n".join(paths)


def uri_text(uris):
    """Copy as URI: one per line (a URI escapes its own line breaks)."""
    return "\n".join(uris)


def clipboard_argv():
    """wl-copy reading the text from its stdin (action_input() says what):
    an argument would be refused past 128 KiB (MAX_ARG_STRLEN), and a text
    that starts with a dash could be taken for an option. text/plain, as
    system-info.py's copy, so wl-copy does not guess the type."""
    return ["wl-copy", "--type", "text/plain"]


def in_scope(argv, which=shutil.which):
    """`argv` in a systemd scope of its own, as uwsm starts every app
    (launcher.py's in_scope, same reason): a terminal or an editor started
    from Files must not live in Nautilus's unit and end with it."""
    if which("uwsm"):
        return ["uwsm", "app", "--"] + list(argv)
    if which("systemd-run"):
        return ["systemd-run", "--user", "--scope", "--quiet", "--"] + list(argv)
    return list(argv)


def action_argv(key, items, which=shutil.which):
    """The command an item runs (None: no such item). items: the selection
    (the folder's one entry for a background click). The clipboard items'
    wl-copy runs as it is, not in a scope: it is gone the moment the next
    copy takes over, and cliphist keeps the text anyway."""
    paths = [i["path"] for i in items]
    if key == "terminal":
        return in_scope([DEFAULT_APPS, "run", "terminal", "--dir", paths[0]], which)
    if key == "editor":
        # absolute paths: never taken for default-apps.py's --dry-run
        return in_scope([DEFAULT_APPS, "run", "editor"] + [os.path.abspath(p) for p in paths], which)
    if key == "wallpaper":
        return in_scope([SELF, "wallpaper", paths[0]], which)
    if key == "ask":
        return in_scope([SELF, "ask", paths[0]], which)
    if key in ("copy-path", "copy-uri"):
        return clipboard_argv()
    return None


def action_input(key, items):
    """What an item's command reads on its stdin, or None (nothing: stdin
    is not even opened). Only the clipboard items have one."""
    if key == "copy-path":
        return path_text([i["path"] for i in items])
    if key == "copy-uri":
        return uri_text([i["uri"] for i in items])
    return None


# Git
def find_repo(directory, exists=os.path.exists):
    """The work tree `directory` is in (the nearest folder above it, or it,
    with a .git -- a folder, or a file in a worktree / submodule), or None.
    Inside .git itself: None (those are git's files, not the project's)."""
    directory = os.path.normpath(directory)
    if ".git" in directory.split(os.sep):
        return None
    probe = directory
    while True:
        if exists(os.path.join(probe, ".git")):
            return probe
        parent = os.path.dirname(probe)
        if parent == probe:
            return None
        probe = parent


def status_argv(directory):
    """One git status for one folder: porcelain v1 with NUL ends (no
    quoting, any byte in a name), limited to that folder (pathspec "."),
    untracked folders as one entry, no optional locks."""
    return ["git", "--no-optional-locks", "-C", directory, "status", "--porcelain=v1", "-z",
            "--untracked-files=normal", "--", "."]


def parse_porcelain(data):
    """`git status --porcelain=v1 -z` -> [(XY, path)], paths relative to the
    work tree's root as str (bytes git cannot name in UTF-8 come back as
    os.fsdecode gives them, matching what os.listdir says). A rename or a
    copy is followed by its old name, which is skipped."""
    if isinstance(data, str):
        data = data.encode("utf-8", "surrogateescape")
    fields = data.split(b"\0")
    out, i = [], 0
    while i < len(fields):
        field = fields[i]
        i += 1
        if len(field) < 4 or field[2:3] != b" ":
            continue
        xy = field[:2].decode("ascii", "replace")
        out.append((xy, os.fsdecode(field[3:])))
        if "R" in xy or "C" in xy:
            i += 1                      # the old name
    return out


def classify(xy):
    """One porcelain XY as a kind (RANK's keys), or None (ignored, clean)."""
    if xy == "??":
        return "untracked"
    if xy == "!!":
        return None
    if xy in CONFLICTS:
        return "conflict"
    x, y = xy[0], xy[1]
    if y in "MT":
        return "modified"
    if y == "D":
        return "deleted"
    if x == "A":
        return "added"
    if x in "RC":
        return "renamed"
    if x == "D":
        return "deleted"
    if x in "MT":
        return "staged"
    return None


def stronger(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return a if RANK[a] >= RANK[b] else b


def dir_statuses(entries, root, directory):
    """{name: kind} for the files and folders directly in `directory`, from
    parse_porcelain() entries of the work tree at `root`. A folder gets the
    strongest kind under it, said as "modified" for anything changed (a
    folder is not "renamed"), "untracked" when all of it is new.
    Inside an untracked folder (git says only "?? new/", for `directory`
    itself or a folder above it) every name is untracked: {EVERYTHING:
    "untracked"}, which kind_for() gives any name."""
    rel = os.path.relpath(os.path.normpath(directory), os.path.normpath(root))
    prefix = "" if rel == "." else rel + "/"
    out = {}
    for xy, path in entries:
        kind = classify(xy)
        if kind == "untracked" and prefix and path.endswith("/") and prefix.startswith(path):
            out[EVERYTHING] = "untracked"
            continue
        if kind is None or not path.startswith(prefix):
            continue
        rest = path[len(prefix):]
        child, _, below = rest.partition("/")
        if not child:
            continue
        if below:                       # something inside the folder `child`
            kind = kind if kind in ("conflict", "untracked") else "modified"
        out[child] = stronger(out.get(child), kind)
    return out


def kind_for(statuses, name):
    """One name's kind from dir_statuses(): its own, or the whole folder's."""
    return statuses.get(name) or statuses.get(EVERYTHING)


def column_text(kind):
    return LABELS.get(kind, "")


def emblem(kind):
    return EMBLEMS.get(kind)


def cache_fresh(cached, stamp, file_mtime, now, ttl=CACHE_TTL):
    """Is a folder's kept git answer still good for this file? cached is
    (stamp, taken, statuses): stamp the folder's and the index's mtimes
    when it was asked, taken the time.time() then. A new stamp (a file
    added, renamed or removed, a commit, a `git add`), a file changed after
    the answer was taken (an edit in place leaves the folder's mtime
    alone) or an answer older than ttl: ask again. A file dated in the
    future (unpacked from a tarball, copied from a camera whose clock is
    ahead) says nothing about when it changed: the stamp and ttl decide,
    or every such file would ask git again, one run per file."""
    if not cached:
        return False
    old_stamp, taken, _statuses = cached
    if old_stamp != stamp or now - taken > ttl:
        return False
    return file_mtime is None or file_mtime <= taken or file_mtime > now


def under_video(outputs, folders, video, on, isfile=os.path.isfile):
    """The monitors where the theme's moving wallpaper plays over
    hyprpaper's still (as wallpaper-slideshow.py's Motion.step decides: the
    switch on and that monitor's folder holding the theme's video), so a
    new still there is set but not seen. folders: {output: its wallpaper
    folder}. Gamemode is not asked: it stops the video only while it
    lasts, and the still is hidden again after."""
    if not (video and on):
        return []
    return [o for o in outputs if folders.get(o) and isfile(os.path.join(folders[o], video))]


# -- the system -------------------------------------------------------------------------------
def dir_stamp(directory, root):
    """(the folder's mtime, the index's mtime) in ns; 0 for one that cannot
    be read (a worktree's index lives elsewhere: its folder and CACHE_TTL
    still apply)."""
    out = []
    for path in (directory, os.path.join(root, ".git", "index")):
        try:
            out.append(os.stat(path).st_mtime_ns)
        except OSError:
            out.append(0)
    return tuple(out)


def notify(title, body="", icon="system-file-manager"):
    try:
        subprocess.run([NOTIFY, "-a", "Files", "-i", icon, "-t", "5000", title, body],
                       capture_output=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        pass


def tilde(path):
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if path == home or path.startswith(home + "/") else path


def connected_outputs(run=subprocess.run):
    """The monitors wallpaper-slideshow.py sees connected, whether its
    rotation is on ("auto") and each one's wallpaper folder: ([names], auto,
    {name: folder})."""
    try:
        proc = run([SLIDESHOW, "settings"], capture_output=True, text=True, timeout=15)
        data = json.loads(proc.stdout or "{}")
    except (OSError, ValueError, subprocess.SubprocessError):
        return [], False, {}
    every = data.get("outputs") or {}
    outputs = sorted(name for name, info in every.items() if info.get("connected"))
    folders = {name: info.get("folder") or "" for name, info in every.items()}
    return outputs, bool(data.get("auto", True)), folders


def motion_state(run=subprocess.run):
    """The theme's moving wallpaper: (video file name or "", switch on),
    from wallpaper-slideshow.py `motion` (no argument: it only says)."""
    try:
        proc = run([SLIDESHOW, "motion"], capture_output=True, text=True, timeout=15)
        data = json.loads(proc.stdout or "{}")
    except (OSError, ValueError, subprocess.SubprocessError):
        return "", False
    return data.get("video") or "", bool(data.get("on"))


def set_wallpaper(path, run=subprocess.run, say=notify):
    """Set as Wallpaper: the picture on every connected monitor, through
    wallpaper-slideshow.py `show` (the daemon's clock restarts; without the
    daemon it asks hyprpaper itself). Returns the exit status."""
    path = os.path.abspath(path)
    if not os.path.isfile(path) or not safe_name(path):
        say("Not set as wallpaper", f"{tilde(path)} is not a picture file hyprpaper can be given")
        return 1
    outputs, auto, folders = connected_outputs(run)
    if not outputs:
        say("Not set as wallpaper", "No monitor answered (is Hyprland running?)")
        return 1
    failed = []
    for output in outputs:
        try:
            proc = run([SLIDESHOW, "show", output, path], capture_output=True, text=True, timeout=20)
            if proc.returncode:
                failed.append(f"{output}: {(proc.stderr or proc.stdout or '').strip() or 'failed'}")
        except (OSError, subprocess.SubprocessError) as exc:
            failed.append(f"{output}: {exc}")
    if len(failed) == len(outputs):
        say("Not set as wallpaper", "\n".join(failed))
        return 1
    body = os.path.basename(path) + (" -- until the slideshow's next change" if auto else "")
    if failed:
        body += "\nNot on " + "; ".join(failed)
    # Set there as well (it shows the moment the video is switched off),
    # but said: on those monitors nothing visible changed.
    hidden = [o for o in under_video(outputs, folders, *motion_state(run))
              if not any(f.startswith(o + ":") for f in failed)]
    if hidden:
        body += ("\nNot visible on " + ", ".join(hidden)
                 + ": the moving wallpaper plays over it (Settings > Wallpaper > Moving wallpaper)")
    say("Wallpaper set", body, "preferences-desktop-wallpaper")
    return 0


def file_mime(path):
    try:
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio
        info = Gio.File.new_for_path(path).query_info("standard::content-type,standard::type",
                                                      Gio.FileQueryInfoFlags.NONE, None)
        return info.get_content_type() or "", info.get_file_type() == Gio.FileType.DIRECTORY
    except Exception:  # noqa: BLE001 -- no Gio / unreadable: the rules treat it as unknown
        return "", os.path.isdir(path)


def ask_about(path, run=subprocess.run, execv=os.execv, say=notify, mime=None):
    """Ask the Local Model: a picture goes to screen-ask.py `image` (the
    file stays where it is: it is not ours to delete, so no --delete), a
    text file's first TEXT_BYTES to screen-ask.py `text`. Secret-looking
    and system files are never handed over (folder_access.refused)."""
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        say("Not asked", f"{tilde(path)} is not a file")
        return 1
    try:
        import folder_access
        why = folder_access.refused(path)
    except ImportError:
        why = None
    if why:
        say("Not asked", f"{tilde(path)} {why}", "dialog-question")
        return 1
    mime = mime if mime is not None else file_mime(path)[0]
    if mime in ASK_IMAGE_TYPES:
        execv(SCREEN_ASK, [SCREEN_ASK, "image", path])
        return 0
    try:
        with open(path, "rb") as handle:
            data = handle.read(TEXT_BYTES)
    except OSError as exc:
        say("Not asked", f"{tilde(path)}: {exc.strerror or exc}")
        return 1
    if b"\0" in data:
        say("Not asked", f"{os.path.basename(path)} is not text", "dialog-question")
        return 1
    # A name that is not UTF-8 comes back surrogate-escaped: said with
    # U+FFFD there, and the text sent as bytes, so no encode can fail.
    name = os.fsencode(os.path.basename(path)).decode("utf-8", "replace")
    text = f"File: {name}\n\n" + data.decode("utf-8", "replace")
    proc = run([SCREEN_ASK, "text"], input=text.encode("utf-8"))
    return proc.returncode


def git_statuses(directory, run=subprocess.run):
    """The Git column for one folder, the slow way (the CLI; the extension
    runs the same git asynchronously)."""
    root = find_repo(directory)
    if root is None:
        return {}
    proc = run(status_argv(directory), capture_output=True, timeout=GIT_TIMEOUT_MS / 1000)
    return dir_statuses(parse_porcelain(proc.stdout), root, directory) if proc.returncode == 0 else {}


def main(argv):
    cmd, args = (argv[0], argv[1:]) if argv else ("", [])
    if cmd == "items" and args:
        items = []
        for path in args:
            path = os.path.abspath(path)
            mime, is_dir = file_mime(path)
            items.append(entry("file://" + urllib.parse.quote(path), path, is_dir, mime))
        for key, label, _tip in file_items(items):
            print(f"{label:22} {action_argv(key, items)}")
        return 0
    if cmd == "git" and len(args) == 1:
        directory = os.path.abspath(args[0])
        statuses = git_statuses(directory)
        names = set(statuses) - {EVERYTHING}
        if EVERYTHING in statuses:          # inside an untracked folder: all of it
            try:
                names |= set(os.listdir(directory))
            except OSError:
                pass
        for name in sorted(names):
            print(f"{column_text(kind_for(statuses, name)):10} {name}")
        return 0
    if cmd == "wallpaper" and len(args) == 1:
        return set_wallpaper(args[0])
    if cmd == "ask" and len(args) == 1:
        return ask_about(args[0])
    print(__doc__.split("\n\n")[-2], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.path.insert(0, HERE)
    sys.exit(main(sys.argv[1:]))
