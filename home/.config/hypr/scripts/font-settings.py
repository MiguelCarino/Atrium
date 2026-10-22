#!/usr/bin/env python3
"""Fonts, text rendering and the pointer, everywhere the desktop draws them
(the Settings window's "Fonts & text" page; the search bar can run it too).

    font-settings.py status              everything below, as JSON
    font-settings.py families [--mono] [--json]
                                         the installed families (fc-list), one
                                         per line; --mono only the monospaced
                                         (and dual-width CJK) ones; --json both
                                         lists and which have a Bold face
    font-settings.py cursors             the installed cursor themes

  Fonts in apps (each one: a family name exactly as `families` prints it, or
  "default" for the stock one; sizes in points):
    font-settings.py set interface <family|default> [size]
    font-settings.py set document  <family|default> [size]
    font-settings.py set monospace <family|default> [size]
    font-settings.py set serif     <family|default>
    font-settings.py size interface|document|monospace <points>

  Rendering:
    font-settings.py scale <0.5-3.0>     text scaling factor
    font-settings.py antialias none|grayscale|rgba
    font-settings.py hinting none|slight|medium|full
    font-settings.py subpixel rgb|bgr|vrgb|vbgr
    font-settings.py rendering default   back to the toolkit's own choice

  The desktop's own text (bar, toolbox, panels, launcher, wofi, mako,
  COSMIC Terminal, kitty) -- the theme's faces unless you pick one:
    font-settings.py desktop font|mono|term <family|theme>
    font-settings.py desktop term-size <px|theme>
    font-settings.py desktop theme       all of them back to the theme's
    font-settings.py desktop apps        the apps' interface and monospace
                                         faces for the desktop too

  The pointer:
    font-settings.py cursor <name|theme> a cursor theme (`cursors`), or the
                                         desktop theme's own
    font-settings.py cursor-size <px>    8-256 (24 is the default)

  Whole:
    font-settings.py reset               every one of the above to default
    font-settings.py snapshot            every setting this script touches,
                                         as JSON (exact: which keys were
                                         unset, which files were missing)
    font-settings.py restore <file|->    put a snapshot back exactly

Where each setting goes
-----------------------
There is no one place every toolkit reads, so each choice is written to
every place that matters, and `status` reads them back from there (this
script keeps no state of its own):

  interface   gsettings org.gnome.desktop.interface font-name (GTK3, GTK4,
              libadwaita, Firefox's chrome, Electron), qt5ct / qt6ct [Fonts]
              general (Qt; at the text scaling factor, since Qt ignores
              GNOME's), fontconfig's sans-serif alias (every app that just
              asks for "sans-serif": Hyprland's own text, web pages, plain
              X11 / SDL programs), COSMIC apps' interface_font (libcosmic:
              COSMIC Files, Edit, the terminal's menus)
  document    gsettings document-font-name (what libadwaita and GNOME apps
              use for reading text)
  monospace   gsettings monospace-font-name, qt?ct [Fonts] fixed,
              fontconfig's monospace alias, COSMIC's monospace_font
  serif       fontconfig's serif alias only (no toolkit has a setting)
  scale       gsettings text-scaling-factor (GTK, libadwaita); Qt's sizes
              are multiplied by it instead
  antialias / hinting / subpixel
              gsettings font-antialiasing / font-hinting / font-rgba-order
              with font-rendering=manual (GTK 4.16+ ignores the three under
              "automatic"), and the same in fontconfig (Qt, kitty, Chrome,
              everything else that renders with FreeType)
  desktop     display.conf font_user, font_mono_user, term_font_user,
              term_font_size_user, read by theme.py over every theme ("Your
              own fonts and cursor" in its docstring), then `theme.py fonts`
              regenerates the stylesheets, mako and the terminals
  cursor      display.conf cursor_theme_user / cursor_size, then `theme.py
              cursor`: gsettings cursor-theme / cursor-size and hyprctl
              setcursor, live; lua/env.lua and ~/.config/uwsm/env read the
              same keys for XCURSOR_THEME / XCURSOR_SIZE / HYPRCURSOR_SIZE at
              login, so it survives a reload and a re-login

The fontconfig file is ~/.config/fontconfig/conf.d/50-desktop-fonts.conf
(this script's alone; deleted when nothing in it is set). 50, so it is read
before the system's 60-latin.conf prefer lists, and before the win95 theme's
60-w95fa-pixels.conf, which still wins for the programs it names.
"""
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import theme  # noqa: E402  (display.conf, the user layer, apply_text / apply_cursor; no GTK)

HOME = os.path.expanduser("~")
CONFIG = os.environ.get("XDG_CONFIG_HOME") or os.path.join(HOME, ".config")
FONTCONFIG = os.path.join(CONFIG, "fontconfig", "conf.d", "50-desktop-fonts.conf")
QT_CONFS = {5: os.path.join(CONFIG, "qt5ct", "qt5ct.conf"), 6: os.path.join(CONFIG, "qt6ct", "qt6ct.conf")}
COSMIC_TK = os.path.join(CONFIG, "cosmic", "com.system76.CosmicTk", "v1")
SCHEMA = "org.gnome.desktop.interface"

# role -> gsettings key; the stock values are only for showing "default".
ROLE_KEYS = {"interface": "font-name", "document": "document-font-name", "monospace": "monospace-font-name"}
DEFAULT_SIZE = {"interface": 11, "document": 12, "monospace": 11}
# fontconfig generic name per role that has one.
ALIASES = {"interface": "sans-serif", "serif": "serif", "monospace": "monospace"}
RENDER_KEYS = {"antialias": ("font-antialiasing", ("none", "grayscale", "rgba")),
               "hinting": ("font-hinting", ("none", "slight", "medium", "full")),
               "subpixel": ("font-rgba-order", ("rgb", "bgr", "vrgb", "vbgr"))}
# Every gsettings key this script writes (snapshot / restore / reset).
GS_KEYS = list(ROLE_KEYS.values()) + [k for k, _ in RENDER_KEYS.values()] + [
    "font-rendering", "text-scaling-factor", "cursor-theme", "cursor-size"]
DESKTOP_KEYS = {"font": "font_user", "mono": "font_mono_user", "term": "term_font_user",
                "term-size": "term_font_size_user"}
STATE_KEYS = list(DESKTOP_KEYS.values()) + ["cursor_theme_user", "cursor_size"]
COSMIC_FILES = {"interface": "interface_font", "monospace": "monospace_font"}
# Words Pango reads as style, not family, at the end of a description.
STYLE_WORDS = {"normal", "roman", "oblique", "italic", "small-caps", "ultra-light", "extra-light", "light",
               "semi-light", "demi-light", "book", "regular", "medium", "semi-bold", "demi-bold", "bold",
               "ultra-bold", "extra-bold", "heavy", "black", "ultra-condensed", "extra-condensed",
               "condensed", "semi-condensed", "semi-expanded", "expanded", "extra-expanded",
               "ultra-expanded", "thin", "ultra-black", "semibold", "extrabold", "extralight",
               "ultralight", "ultrabold", "ultraheavy", "demibold", "not-rotated", "south", "upside-down",
               "north", "rotated-left", "east", "rotated-right", "west"}
MARK = "GENERATED by ~/.config/hypr/scripts/font-settings.py"


# -- pure helpers (tests/test_settings_fonts.py) -----------------------------------
def parse_desc(desc):
    """A Pango font description -> (family, style words, size or None):
    "Adwaita Sans 11" -> ("Adwaita Sans", "", 11.0); "Cantarell Bold 10.5" ->
    ("Cantarell", "Bold", 10.5); "Font 5, 11" -> ("Font 5", "", 11.0) (the
    comma ends the family list, Pango's own way to keep a family that ends
    in a number)."""
    desc = (desc or "").strip()
    if "," in desc:
        family, _, rest = desc.rpartition(",")
        words = rest.split()
        family = family.split(",")[0].strip()
    else:
        words = desc.split()
        family = None
    size = None
    if words and re.fullmatch(r"\d+(\.\d+)?(px)?", words[-1]):
        size = float(words.pop().removesuffix("px"))
    styles = []
    if family is None:
        while len(words) > 1 and words[-1].lower() in STYLE_WORDS:
            styles.insert(0, words.pop())
        family = " ".join(words)
    else:
        styles = [w for w in words if w.lower() in STYLE_WORDS]
    return family, " ".join(styles), size


def format_size(size):
    return f"{size:g}"


def make_desc(family, size, styles=""):
    """The other way. A family whose last word Pango would take for a size
    or a style gets the comma."""
    last = family.split()[-1].lower() if family.split() else ""
    tail = " ".join(p for p in (styles, format_size(size)) if p)
    if re.fullmatch(r"\d+(\.\d+)?(px)?", last) or last in STYLE_WORDS or styles:
        return f"{family}, {tail}"
    return f"{family} {tail}"


def qt_font(family, size, qt):
    """QFont::toString() as qt5ct / qt6ct store it: Qt 5's ten fields
    (weight 50 = Normal), Qt 6's sixteen (weight 400)."""
    size = format_size(round(size * 2) / 2)
    if qt == 5:
        return f'"{family},{size},-1,5,50,0,0,0,0,0"'
    return f'"{family},{size},-1,5,400,0,0,0,0,0,0,0,0,0,0,1"'


def parse_qt_font(value):
    """'"Inter,11,-1,5,50,0,0,0,0,0"' -> ("Inter", 11.0); None if unset."""
    value = (value or "").strip().strip('"')
    parts = value.split(",")
    if len(parts) < 2 or not parts[0]:
        return None
    try:
        return parts[0], float(parts[1])
    except ValueError:
        return parts[0], None


def ini_get(text, section, key):
    current = None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            current = s[1:-1]
        elif current == section and s.partition("=")[0].strip() == key and "=" in s:
            return s.partition("=")[2].strip()
    return None


def ini_set(text, section, key, value):
    """The ini text with section/key set to value (None removes it); every
    other line kept as it was. A missing section is added at the end; a
    section a removal leaves empty goes too."""
    lines = text.split("\n") if text else []
    header = lambda s: s.strip().startswith("[") and s.strip().endswith("]")
    start = next((i for i, l in enumerate(lines) if l.strip() == f"[{section}]"), None)
    if start is None:
        if value is None:
            return text
        while lines and not lines[-1].strip():
            lines.pop()
        tail = [""] if lines else []
        return "\n".join(lines + tail + [f"[{section}]", f"{key}={value}", ""])
    end = next((i for i in range(start + 1, len(lines)) if header(lines[i])), len(lines))
    body = [l for l in lines[start + 1:end] if l.partition("=")[0].strip() != key or "=" not in l]
    if value is not None:
        at = len(body)
        while at and not body[at - 1].strip():
            at -= 1
        body.insert(at, f"{key}={value}")
    if not any(l.strip() for l in body):
        before = lines[:start]
        if end == len(lines):
            while before and not before[-1].strip():
                before.pop()
            return "\n".join(before + ([""] if before else []))
        return "\n".join(before + lines[end:])
    return "\n".join(lines[:start + 1] + body + lines[end:])


def render_props(antialias, hinting, subpixel):
    """gsettings' three rendering keys -> fontconfig's properties:
    [(name, type, value)] as <edit name=... mode="assign"><type>value</type>."""
    props = [("antialias", "bool", "false" if antialias == "none" else "true"),
             ("hinting", "bool", "false" if hinting == "none" else "true"),
             ("hintstyle", "const", "hint" + (hinting if hinting in ("none", "slight", "medium", "full") else "slight")),
             ("rgba", "const", subpixel if antialias == "rgba" else "none"),
             ("lcdfilter", "const", "lcddefault" if antialias == "rgba" else "lcdnone")]
    return props


def fontconfig_text(aliases, rendering):
    """The whole fontconfig file: aliases {generic: family} prefer the
    family for that generic name; rendering (antialias, hinting, subpixel)
    or None. None when there is nothing to say (the file goes away)."""
    aliases = {k: v for k, v in (aliases or {}).items() if v}
    if not aliases and not rendering:
        return None
    esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    out = ['<?xml version="1.0"?>', '<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">',
           # (No double hyphen inside an XML comment: fontconfig rejects the file.)
           f"<!-- {MARK}; do not edit.",
           '     The Settings window\'s "Fonts and text" page; font-settings.py help. -->',
           "<fontconfig>"]
    for generic in ("sans-serif", "serif", "monospace"):
        if generic in aliases:
            out += [f"  <alias binding=\"strong\">", f"    <family>{generic}</family>",
                    f"    <prefer><family>{esc(aliases[generic])}</family></prefer>", "  </alias>"]
    if rendering:
        out.append(f'  <!-- rendering: antialias={rendering[0]} hinting={rendering[1]} subpixel={rendering[2]} -->')
        out.append('  <match target="font">')
        for name, kind, value in render_props(*rendering):
            out.append(f'    <edit name="{name}" mode="assign"><{kind}>{value}</{kind}></edit>')
        out.append("  </match>")
    out.append("</fontconfig>")
    return "\n".join(out) + "\n"


def fontconfig_read(text):
    """fontconfig_text's answer back: (aliases, rendering or None). Only
    this script's own file is read this way; anything unexpected is None."""
    aliases, rendering = {}, None
    if not text:
        return aliases, rendering
    m = re.search(r"rendering: antialias=(\w+) hinting=(\w+) subpixel=(\w+)", text)
    if m:
        rendering = (m[1], m[2], m[3])
    try:
        root = ET.fromstring(re.sub(r"<!DOCTYPE[^>]*>", "", text))
    except ET.ParseError:
        return aliases, rendering
    for alias in root.findall("alias"):
        generic = alias.findtext("family")
        pref = alias.find("prefer")
        if generic and pref is not None and pref.findtext("family"):
            aliases[generic.strip()] = pref.findtext("family").strip()
    return aliases, rendering


def cosmic_font(family):
    """libcosmic's FontConfig as RON (COSMIC Settings writes the same)."""
    fam = family.replace("\\", "\\\\").replace('"', '\\"')
    return f'(\n    family: "{fam}",\n    weight: Normal,\n    stretch: Normal,\n    style: Normal,\n)'


def cosmic_family(text):
    m = re.search(r'family:\s*"((?:[^"\\]|\\.)*)"', text or "")
    return m[1].replace('\\"', '"').replace("\\\\", "\\") if m else None


def parse_families(text):
    """fc-list -f '%{family[0]}|%{spacing}|%{color}|%{weight}\\n' ->
    {"all": [...], "mono": [...], "bold": [...]}, each sorted, case-blind.
    Monospaced = any face with spacing 100 (mono) or 90 (dual: CJK
    monospace, wide glyphs two cells), colour (emoji) faces left out."""
    all_, mono, bold = set(), set(), set()
    for line in (text or "").splitlines():
        parts = line.split("|")
        fam = parts[0].strip()
        if not fam:
            continue
        all_.add(fam)
        spacing = parts[1].strip() if len(parts) > 1 else ""
        color = parts[2].strip().lower() if len(parts) > 2 else ""
        if spacing in ("90", "100") and color != "true":
            mono.add(fam)
        try:
            weights = [float(w) for w in re.findall(r"[\d.]+", parts[3])] if len(parts) > 3 else []
        except ValueError:
            weights = []
        if any(w >= 200 for w in weights):
            bold.add(fam)
    key = lambda s: s.casefold()
    return {"all": sorted(all_, key=key), "mono": sorted(mono, key=key), "bold": sorted(bold, key=key)}


def canonical(family, names):
    """The installed name for `family`, matched case-blind; None if absent."""
    want = (family or "").strip().casefold()
    return next((n for n in names if n.casefold() == want), None)


def gvariant_str(raw):
    """gsettings get's 'Adwaita Sans 11' -> Adwaita Sans 11."""
    raw = (raw or "").strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "'\"":
        return raw[1:-1].replace("\\'", "'").replace('\\"', '"')
    return raw


# -- reading the system --------------------------------------------------------------
def sh(*cmd, timeout=10):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return out.stdout if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


_SETTINGS = None


def settings():
    """org.gnome.desktop.interface through Gio (no GTK): one process, and
    get_user_value() tells a key you set from one left at its default,
    which the gsettings CLI cannot."""
    global _SETTINGS
    if _SETTINGS is None:
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio
        _SETTINGS = Gio.Settings.new(SCHEMA)
        _SETTINGS.keys = set(_SETTINGS.props.settings_schema.list_keys())
    return _SETTINGS


def gs_all():
    """{key: value as gsettings prints it} for the keys this script reads."""
    s = settings()
    keys = set(GS_KEYS)
    return {k: s.get_value(k).print_(False) for k in keys if k in s.keys}


def gs_user():
    """{key: printed value} for the keys set by the user (not at default)."""
    s = settings()
    out = {}
    for k in GS_KEYS:
        if k in s.keys:
            v = s.get_user_value(k)
            if v is not None:
                out[k] = v.print_(False)
    return out


def gs_set(key, value):
    """value as the gsettings CLI takes it ('Inter 11', 1.25, rgba): strings
    are quoted here for the string keys, so callers pass plain text."""
    from gi.repository import GLib
    s = settings()
    if key not in s.keys:
        return False
    kind = s.get_value(key).get_type_string()
    if kind == "s":
        variant = GLib.Variant("s", str(value))
    elif kind == "d":
        variant = GLib.Variant("d", float(value))
    elif kind == "i":
        variant = GLib.Variant("i", int(value))
    elif kind == "u":
        variant = GLib.Variant("u", int(value))
    else:
        variant = GLib.Variant.parse(GLib.VariantType.new(kind), str(value), None, None)
    ok = s.set_value(key, variant)
    s.sync()
    return ok


def gs_set_raw(key, raw):
    """A printed value back (snapshot / restore)."""
    from gi.repository import GLib
    s = settings()
    if key in s.keys:
        s.set_value(key, GLib.Variant.parse(s.get_value(key).get_type(), raw, None, None))
        s.sync()


def gs_reset(key):
    s = settings()
    if key in s.keys:
        s.reset(key)
        s.sync()


def families():
    text = sh("fc-list", "-f", "%{family[0]}|%{spacing}|%{color}|%{weight}\n") or ""
    return parse_families(text)


def fc_match(generic):
    return (sh("fc-match", "-f", "%{family[0]}", generic) or "").strip() or None


def read(path):
    try:
        with open(path) as handle:
            return handle.read()
    except OSError:
        return None


def write(path, text):
    """Atomic; None deletes."""
    if text is None:
        try:
            os.remove(path)
        except OSError:
            pass
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as handle:
        handle.write(text)
    os.replace(tmp, path)


def cursor_themes():
    """Installed cursor themes: icon-theme folders with a cursors/ inside."""
    data = [os.path.join(HOME, ".local", "share")]
    data += (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":")
    roots = [os.path.join(HOME, ".icons")] + [os.path.join(d, "icons") for d in data]
    names = set()
    for root in roots:
        try:
            for name in os.listdir(root):
                if os.path.isdir(os.path.join(root, name, "cursors")) and name != "default":
                    names.add(name)
        except OSError:
            pass
    return sorted(names, key=str.casefold)


# -- writing ---------------------------------------------------------------------------
def fontconfig_update(alias=None, family=None, rendering="keep"):
    aliases, render = fontconfig_read(read(FONTCONFIG))
    if alias:
        aliases[alias] = family
    if rendering != "keep":
        render = rendering
    write(FONTCONFIG, fontconfig_text(aliases, render))


def qt_update(key, family, size):
    """[Fonts] general/fixed in both qt?ct configs; family None removes it.
    Only configs that exist: qt?ct makes its own on first start."""
    for qt, path in QT_CONFS.items():
        text = read(path)
        if text is None:
            continue
        value = qt_font(family, size, qt) if family else None
        new = ini_set(text, "Fonts", key, value)
        if new != text:
            write(path, new)


def cosmic_update(role, family):
    if role in COSMIC_FILES:
        write(os.path.join(COSMIC_TK, COSMIC_FILES[role]), cosmic_font(family) if family else None)


def scale_now(gs=None):
    gs = gs if gs is not None else gs_all()
    try:
        return float(gs.get("text-scaling-factor", "1.0"))
    except ValueError:
        return 1.0


def role_now(role, gs):
    family, styles, size = parse_desc(gvariant_str(gs.get(ROLE_KEYS[role], "")))
    return family, styles, size or DEFAULT_SIZE[role]


def qt_follow(gs=None):
    """Qt's two fonts from gsettings' interface / monospace, at the text
    scaling factor -- whenever the user changed anything Qt would otherwise
    miss: picked the face (an alias in our fontconfig file says so), set
    its size (the gsettings key is no longer at its default, even with the
    stock face), or a text scaling factor other than 1 (Qt ignores GNOME's,
    so without a size of its own a Qt app would stay small). With none of
    those, Qt keeps its own default and the key goes."""
    gs = gs if gs is not None else gs_all()
    aliases, _ = fontconfig_read(read(FONTCONFIG))
    user = gs_user()
    scale = scale_now(gs)
    for role, key in (("interface", "general"), ("monospace", "fixed")):
        if aliases.get(ALIASES[role]) or ROLE_KEYS[role] in user or abs(scale - 1.0) > 0.001:
            family, _, size = role_now(role, gs)
            qt_update(key, family, size * scale)
        else:
            qt_update(key, None, 0)


def set_role(role, family, size=None):
    if role == "serif":
        if family == "default":
            fontconfig_update("serif", None)
            return "serif: the system's default"
        name = canonical(family, families()["all"])
        if not name:
            sys.exit(f"font-settings: no installed family {family!r} (font-settings.py families)")
        fontconfig_update("serif", name)
        return f"serif: {name}"
    if role not in ROLE_KEYS:
        sys.exit(f"font-settings: no role {role!r} (interface, document, monospace, serif)")
    key = ROLE_KEYS[role]
    if family == "default":
        gs_reset(key)
        if role in ALIASES:
            fontconfig_update(ALIASES[role], None)
        cosmic_update(role, None)
        qt_follow()
        return f"{role}: default"
    fams = families()
    name = canonical(family, fams["all"])
    if not name:
        sys.exit(f"font-settings: no installed family {family!r} (font-settings.py families)")
    gs = gs_all()
    _, styles, now = role_now(role, gs)
    size = float(size) if size else now
    if not 4 <= size <= 72:
        sys.exit("font-settings: a size is 4-72 points")
    gs_set(key, make_desc(name, size))
    if role in ALIASES:
        fontconfig_update(ALIASES[role], name)
    cosmic_update(role, name)
    qt_follow()
    warn = ""
    if role == "monospace" and name not in fams["mono"]:
        warn = "  (not a monospaced face: columns will not line up)"
    return f"{role}: {make_desc(name, size)}{warn}"


def set_size(role, size):
    if role not in ROLE_KEYS:
        sys.exit("font-settings: size interface|document|monospace <points>")
    try:
        size = float(size)
    except ValueError:
        sys.exit("font-settings: a size is a number of points")
    if not 4 <= size <= 72:
        sys.exit("font-settings: a size is 4-72 points")
    gs = gs_all()
    family, styles, _ = role_now(role, gs)
    gs_set(ROLE_KEYS[role], make_desc(family, size, styles))
    qt_follow()
    return f"{role}: {make_desc(family, size, styles)}"


def set_scale(value):
    try:
        value = float(value)
    except ValueError:
        sys.exit("font-settings: scale is a number, 0.5-3.0")
    if not 0.5 <= value <= 3.0:
        sys.exit("font-settings: scale is 0.5-3.0")
    if abs(value - 1.0) < 0.001:
        gs_reset("text-scaling-factor")
    else:
        gs_set("text-scaling-factor", f"{value:.2f}")
    qt_follow()
    return f"scale: {value:g}"


def set_render(what, value):
    key, allowed = RENDER_KEYS[what]
    if value not in allowed:
        sys.exit(f"font-settings: {what} is one of {', '.join(allowed)}")
    gs_set(key, value)
    gs_set("font-rendering", "manual")
    gs = gs_all()
    now = tuple(gvariant_str(gs.get(RENDER_KEYS[k][0], "")) for k in ("antialias", "hinting", "subpixel"))
    fontconfig_update(rendering=now)
    return f"{what}: {value}"


def reset_render():
    for k, _ in RENDER_KEYS.values():
        gs_reset(k)
    gs_reset("font-rendering")
    fontconfig_update(rendering=None)
    return "rendering: default"


def set_desktop(what, value):
    state = theme.read_state()
    if what == "theme":
        for k in DESKTOP_KEYS.values():
            state.pop(k, None)
    elif what == "apps":
        gs = gs_all()
        fams = families()
        ui, _, _ = role_now("interface", gs)
        mono, _, _ = role_now("monospace", gs)
        state["font_user"] = canonical(ui, fams["all"]) or ""
        state["font_mono_user"] = canonical(mono, fams["all"]) or ""
        # The terminal only if the apps' monospace really is monospaced.
        state["term_font_user"] = canonical(mono, fams["mono"]) or state.get("term_font_user", "")
    elif what in DESKTOP_KEYS:
        if value is None:
            sys.exit(f"font-settings: desktop {what} <{'px' if what == 'term-size' else 'family'}|theme>")
        if value == "theme":
            state.pop(DESKTOP_KEYS[what], None)
        elif what == "term-size":
            if not (value.isdigit() and 6 <= int(value) <= 48):
                sys.exit("font-settings: a terminal size is 6-48 px")
            state[DESKTOP_KEYS[what]] = value
        else:
            fams = families()
            name = canonical(value, fams["all"])
            if not name:
                sys.exit(f"font-settings: no installed family {value!r} (font-settings.py families)")
            if what == "term":
                if name not in fams["mono"]:
                    sys.exit(f"font-settings: {name} is not monospaced; a terminal needs one "
                             "(font-settings.py families --mono)")
            state[DESKTOP_KEYS[what]] = name
    else:
        sys.exit("font-settings: desktop font|mono|term|term-size|theme|apps")
    theme.write_state(state)
    changed = theme.apply_text(theme.load())
    note = ""
    term = theme.load().get("term.font", "")
    if what in ("term", "apps") and term and term not in families()["bold"]:
        note = f"  ({term} has no Bold face: COSMIC Terminal will use its own default)"
    return f"desktop: {', '.join(changed) if changed else 'nothing changed'}{note}"


def set_cursor(value):
    state = theme.read_state()
    if value == "theme":
        state.pop("cursor_theme_user", None)
    else:
        name = canonical(value, cursor_themes())
        if not name:
            sys.exit(f"font-settings: no cursor theme {value!r} (have: {', '.join(cursor_themes())})")
        state["cursor_theme_user"] = name
    theme.write_state(state)
    conf = theme.load()
    theme.apply_cursor(conf, force=True)
    return f"cursor: {conf.get('cursor_theme')} {theme.cursor_size()}"


def set_cursor_size(value):
    if not (value.isdigit() and 8 <= int(value) <= 256):
        sys.exit("font-settings: a cursor size is 8-256 px")
    state = theme.read_state()
    state["cursor_size"] = "" if value == theme.CURSOR_SIZE else value
    theme.write_state(state)
    conf = theme.load()
    theme.apply_cursor(conf, force=True)
    return f"cursor: {conf.get('cursor_theme')} {theme.cursor_size()}"


# -- status / snapshot ---------------------------------------------------------------
def status():
    gs = gs_all()
    aliases, rendering = fontconfig_read(read(FONTCONFIG))
    user = gs_user()
    out = {"roles": {}}
    for role, key in ROLE_KEYS.items():
        family, styles, size = role_now(role, gs)
        out["roles"][role] = {"family": family, "styles": styles, "size": size,
                              "desc": gvariant_str(gs.get(key, "")), "default": key not in user}
    out["roles"]["serif"] = {"family": aliases.get("serif") or fc_match("serif"), "size": None,
                             "default": not aliases.get("serif")}
    out["fontconfig"] = {"file": FONTCONFIG if os.path.exists(FONTCONFIG) else None, "aliases": aliases,
                         "resolved": {g: fc_match(g) for g in ("sans-serif", "serif", "monospace")}}
    out["scale"] = scale_now(gs)
    out["rendering"] = {"mode": gvariant_str(gs.get("font-rendering", "")) or "automatic",
                        "antialias": gvariant_str(gs.get("font-antialiasing", "")),
                        "hinting": gvariant_str(gs.get("font-hinting", "")),
                        "subpixel": gvariant_str(gs.get("font-rgba-order", "")),
                        "fontconfig": rendering is not None}
    qt = {}
    for v, path in QT_CONFS.items():
        text = read(path)
        qt[f"qt{v}"] = None if text is None else {
            "general": parse_qt_font(ini_get(text, "Fonts", "general")),
            "fixed": parse_qt_font(ini_get(text, "Fonts", "fixed"))}
    out["qt"] = qt
    out["cosmic"] = {role: cosmic_family(read(os.path.join(COSMIC_TK, f))) for role, f in COSMIC_FILES.items()}
    state = theme.read_state()
    conf = theme.load()
    out["desktop"] = {"theme": conf.get("name") or conf["id"]}
    for what, skey in DESKTOP_KEYS.items():
        tkey = theme.USER_KEYS[skey]
        out["desktop"][what] = {"user": state.get(skey) or None, "theme": conf.get(f"theme:{tkey}", ""),
                                "now": conf.get(tkey, "")}
    out["cursor"] = {"now": gvariant_str(gs.get("cursor-theme", "")), "size_now": gs.get("cursor-size", ""),
                     "user": state.get("cursor_theme_user") or None,
                     "theme": conf.get("theme:cursor_theme") or "Adwaita",
                     "size": int(theme.cursor_size(state)), "installed": cursor_themes()}
    return out


def snapshot():
    user = gs_user()
    state = theme.read_state()
    files = [FONTCONFIG] + list(QT_CONFS.values()) + [os.path.join(COSMIC_TK, f) for f in COSMIC_FILES.values()]
    return {"gsettings": {k: user.get(k) for k in GS_KEYS},
            "state": {k: state.get(k) for k in STATE_KEYS},
            "files": {p: read(p) for p in files}}


def restore(snap):
    for key, raw in snap.get("gsettings", {}).items():
        if key not in GS_KEYS:
            continue
        if raw is None:
            gs_reset(key)
        else:
            gs_set_raw(key, raw)
    for path, text in snap.get("files", {}).items():
        allowed = [FONTCONFIG] + list(QT_CONFS.values()) + [os.path.join(COSMIC_TK, f) for f in COSMIC_FILES.values()]
        if path in allowed and read(path) != text:
            write(path, text)
    state = theme.read_state()
    for key, value in snap.get("state", {}).items():
        if key in STATE_KEYS:
            if value:
                state[key] = value
            else:
                state.pop(key, None)
    theme.write_state(state)
    theme.apply_text(theme.load())
    theme.apply_cursor(theme.load(), force=True)
    return "restored"


def reset_all():
    blank = {"gsettings": {k: None for k in GS_KEYS}, "state": {k: None for k in STATE_KEYS},
             "files": {FONTCONFIG: None, **{os.path.join(COSMIC_TK, f): None for f in COSMIC_FILES.values()}}}
    restore(blank)
    for qt, path in QT_CONFS.items():
        text = read(path)
        if text is not None:
            new = ini_set(ini_set(text, "Fonts", "general", None), "Fonts", "fixed", None)
            if new != text:
                write(path, new)
    return "everything back to default"


def main(argv):
    cmd, args = (argv[0], argv[1:]) if argv else ("", [])
    if cmd == "status":
        print(json.dumps(status(), ensure_ascii=False))
    elif cmd == "families":
        fams = families()
        if "--json" in args:
            print(json.dumps(fams, ensure_ascii=False))
        else:
            print("\n".join(fams["mono" if "--mono" in args else "all"]))
    elif cmd == "cursors":
        print("\n".join(cursor_themes()))
    elif cmd == "set" and len(args) in (2, 3):
        print(set_role(args[0], args[1], args[2] if len(args) == 3 else None))
    elif cmd == "size" and len(args) == 2:
        print(set_size(*args))
    elif cmd == "scale" and len(args) == 1:
        print(set_scale(args[0]))
    elif cmd in RENDER_KEYS and len(args) == 1:
        print(set_render(cmd, args[0]))
    elif cmd == "rendering" and args == ["default"]:
        print(reset_render())
    elif cmd == "desktop" and 1 <= len(args) <= 2:
        print(set_desktop(args[0], args[1] if len(args) == 2 else None))
    elif cmd == "cursor" and len(args) == 1:
        print(set_cursor(args[0]))
    elif cmd == "cursor-size" and len(args) == 1:
        print(set_cursor_size(args[0]))
    elif cmd == "reset" and not args:
        print(reset_all())
    elif cmd == "snapshot":
        print(json.dumps(snapshot(), ensure_ascii=False, indent=1))
    elif cmd == "restore" and len(args) == 1:
        text = sys.stdin.read() if args[0] == "-" else read(args[0])
        try:
            snap = json.loads(text or "")
        except ValueError:
            sys.exit("font-settings: not a snapshot (font-settings.py snapshot > file)")
        print(restore(snap))
    else:
        print(__doc__.strip(), file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main(sys.argv[1:])
