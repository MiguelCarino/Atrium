"""The Settings window's list of pages, without GTK: what settings.py's
sidebar and search box, `settings.py --list` and the launcher's
"Settings: <page>" items all read, so they never disagree about which pages
exist or which words find them.

A page's PAGE dict is read here from the page's SOURCE -- just the
`PAGE = {...}` statement, through ast.literal_eval -- rather than by
importing the module: a page imports GTK and the display panel, about
150 ms the launcher should not spend every time it opens. settings.py still
imports every page to build the window, and its sidebar uses the real
(imported) PAGE; the search uses the same rules on both (search() below).
The leading underscore keeps settings.py's discover() from taking this file
for a page.

    python3 -m settings_pages._catalog [words]   the pages (or the ones the
                                                 words find, best first)

Matching: every typed word must be the START of a word of the page's title,
its keywords, its group or its id ("blue" finds Bluetooth, "screen lock"
finds Power & screen lock). Case, accents and hyphens do not count ("wifi"
is "Wi-Fi", "sonido" is "sónido"). A word in the title counts most, then a
keyword, then the group / id, so "sound" puts the Sound page before
Notifications (whose keywords say "notification sound").
"""
import ast
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
# "Smart" first: the Smart desktop hub (intelligence.py), every smart feature's switch on one page.
GROUPS = ["Smart", "Look", "Apps", "Hardware", "System"]

# The display panel's own three pages (waybar/scripts/display_panel.py
# DisplayControls), which settings.py lists like the rest. Their keywords are
# what is on each of them.
BUILTIN = [
    {"id": "screens", "title": "Screens", "icon": "", "group": "Hardware", "order": 5,
     "keywords": ["display", "monitor", "pantalla", "hdr", "sdr", "brightness", "brillo", "dim",
                  "warmth", "colour temperature", "color", "saturation", "red green blue", "night light",
                  "refresh rate", "hz", "resolution", "scale", "rotation", "arrange", "position",
                  "mirror", "vrr", "variable refresh", "adaptive sync", "primary", "main screen",
                  "bit depth", "10 bit", "night light schedule", "screen off"]},
    {"id": "theme", "title": "Theme", "icon": "", "group": "Look", "order": 10, "tab": "Theme",
     "keywords": ["tema", "mpv", "video player", "player border", "mpv frame", "mpv controls", "uosc", "accent", "accent colour", "accent color", "accent from wallpaper", "glass",
                  "transparency", "window glass", "wallpaper", "fondo", "moving wallpaper",
                  "living wallpaper", "theme fade", "theme sounds", "dark", "light", "dark mode",
                  "light mode", "day and night",
                  "time of day", "schedule", "evening"]},
    {"id": "effects", "title": "Effects", "icon": "", "group": "Look", "order": 30, "parent": "theme", "tab": "Effects",
     "keywords": ["screen filter", "shader", "grayscale", "greyscale", "reading", "vibrance", "crt",
                  "colour blindness", "color blind", "protanopia", "deuteranopia", "tritanopia",
                  "animations", "animaciones", "snappy", "smooth", "fancy", "calm", "motion"]},
]


# -- words ------------------------------------------------------------------------------
def fold(text):
    """Lower case, no accents, no hyphens or apostrophes inside a word:
    "Wi-Fi" -> "wifi", "Día" -> "dia", "bar's" -> "bars"."""
    text = unicodedata.normalize("NFKD", str(text))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    return re.sub(r"(?<=\w)[-'’](?=\w)", "", text)


def words(text):
    return re.findall(r"[a-z0-9]+", fold(text))


def _fields(meta):
    """(weight, words) for each part of a page that a search looks at."""
    keywords = meta.get("keywords") or []
    return ((3, words(meta.get("title", ""))),
            (2, [w for k in keywords for w in words(k)]),
            (1, words(meta.get("group", "")) + words(meta.get("id", ""))))


def score(meta, query):
    """How well a page matches the typed words: None when one of them is not
    the start of any word of the page, otherwise higher is better."""
    wanted = words(query)
    if not wanted:
        return 0
    total = 0
    for want in wanted:
        best = 0
        for weight, have in _fields(meta):
            if want in have:
                best = max(best, weight * 2 + 1)        # the whole word beats a beginning
            elif any(w.startswith(want) for w in have):
                best = max(best, weight * 2)
        if not best:
            return None
        total += best
    if words(meta.get("title", ""))[:len(wanted)] == wanted:
        total += 4                                      # "sound" is the Sound page, first
    if any(words(k) == wanted for k in meta.get("keywords") or []):
        total += 2                                      # "hdr" is Screens' keyword; Screenshots' is "hdr recording"
    return total


def hint(meta, query):
    """The keyword that made a page match when its title does not say it
    ("bluetooth" for Network & Bluetooth does; "tap to click" for Keyboard,
    mouse & touchpad does not) -- shown under the result. "" when the title
    alone matches."""
    title = words(meta.get("title", ""))
    missing = [w for w in words(query) if not any(t.startswith(w) for t in title)]
    if not missing:
        return ""
    best, hits = "", 0
    for keyword in meta.get("keywords") or []:
        have = words(keyword)
        n = sum(any(h.startswith(w) for h in have) for w in missing)
        if n > hits:                # the keyword that says the most of what was typed
            best, hits = keyword, n
    return best


def search(pages, query):
    """The pages the typed words find, best first (ties in sidebar order)."""
    order = {p["id"]: n for n, p in enumerate(pages)}
    found = [(score(p, query), p) for p in pages]
    found = [(s, p) for s, p in found if s is not None]
    found.sort(key=lambda sp: (-sp[0], order[sp[1]["id"]]))
    return [p for _, p in found]


def resolve(pages, arg):
    """`settings.py <arg>`: a page id as it is, else the best page the words
    find ("bluetooth" -> network), else None."""
    if not arg:
        return None
    if any(p["id"] == arg for p in pages):
        return arg
    found = search(pages, arg)
    return found[0]["id"] if found else None


def sort_key(meta):
    group = meta.get("group")
    return (GROUPS.index(group) if group in GROUPS else len(GROUPS), meta.get("order", 50), meta.get("title", ""))


def arrange(pages):
    """Sidebar order with each page's tabs right after it: a page whose PAGE
    says "parent": <id> is not in the sidebar but a tab of that page (its own
    "tab" is the tab's caption, the parent's "tab" the caption of its first
    tab). A parent that does not exist makes the page an ordinary one."""
    ids = {p["id"] for p in pages}
    top = sorted((p for p in pages if p.get("parent") not in ids), key=sort_key)
    out = []
    for page in top:
        out.append(page)
        out += sorted((p for p in pages if p.get("parent") == page["id"]),
                      key=lambda p: (p.get("order", 50), p.get("title", "")))
    return out


def tabs(pages, host):
    """[(id, caption)] of a sidebar page's tabs, itself first; [] when it
    has none."""
    kids = [p for p in arrange(pages) if p.get("parent") == host]
    if not kids:
        return []
    me = next(p for p in pages if p["id"] == host)
    return [(host, me.get("tab") or me["title"])] + [(p["id"], p.get("tab") or p["title"]) for p in kids]


def host_of(pages, page_id):
    """The sidebar page that shows page_id: its parent, or itself."""
    meta = next((p for p in pages if p["id"] == page_id), None)
    parent = (meta or {}).get("parent")
    return parent if any(p["id"] == parent for p in pages) else page_id


# -- reading the pages without importing them -------------------------------------------
_CACHE = {}         # path -> (mtime, PAGE or None)


def page_of(source):
    """The PAGE dict of a page's source text, or None: the `PAGE = {` line
    and as many lines after it as it takes to close the dict. Only literal
    values count (a PAGE built from variables is left to settings.py's
    import)."""
    lines = source.splitlines()
    for n, line in enumerate(lines):
        if re.match(r"PAGE\s*=\s*\{", line):
            for end in range(n + 1, min(n + 60, len(lines)) + 1):
                try:
                    node = ast.parse("\n".join(lines[n:end]))
                except SyntaxError:
                    continue
                try:
                    page = ast.literal_eval(node.body[0].value)
                except (ValueError, TypeError, SyntaxError, AttributeError, IndexError):
                    return None
                return page if isinstance(page, dict) and "id" in page and "title" in page else None
            return None
    return None


def read_pages(folder=HERE, builtin=True):
    """Every page's PAGE, in sidebar order (each page's tabs after it). A file
    is read again only when it has changed (the launcher asks every time it
    opens)."""
    pages = list(BUILTIN) if builtin else []
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        names = []
    for name in names:
        if not name.endswith(".py") or name.startswith("_") or name == "common.py":
            continue
        path = os.path.join(folder, name)
        try:
            mtime = os.stat(path).st_mtime_ns
            cached = _CACHE.get(path)
            if not cached or cached[0] != mtime:
                with open(path, encoding="utf-8") as handle:
                    cached = _CACHE[path] = (mtime, page_of(handle.read()))
        except OSError:
            continue
        if cached[1]:
            pages.append(cached[1])
    return arrange(pages)


if __name__ == "__main__":
    query = " ".join(sys.argv[1:])
    everything = read_pages()
    for page in (search(everything, query) if query else everything):
        extra = hint(page, query) if query else ""
        print(f"{page['id']}\t{page.get('group', '')}\t{page['title']}" + (f"\t{extra}" if extra else ""))
