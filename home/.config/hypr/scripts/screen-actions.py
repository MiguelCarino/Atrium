#!/usr/bin/env python3
"""Actions for anything on screen: pick a region (its text is read with
OCR) or take the selected text, then choose what to do with it.

    screen-actions.py region      drag a box (slurp); grim + tesseract, in the
                                  languages Settings > Screenshots & recording
                                  picks (eng+spa unless changed)
    screen-actions.py selection   the primary selection (text you highlighted),
                                  else the clipboard

The menu is a card like the popup panels (panelui, panel.css: the theme's
look) in the middle of the focused screen. Up / Down / Enter or a click;
Escape closes. The header shows the start of what was found.

    Copy text         to the clipboard (wl-copy)
    Translate         Spanish <-> English, by the local model (LM Studio)
    Look it up        a web search in the default browser, on the engine
                      Settings picks (DuckDuckGo unless changed)
    Add to calendar   the local model reads a title, day and time out of it;
                      shown for a yes first, then added to Evolution's default
                      calendar (the one timers.py's calendar alarms read), or
                      as an .ics file opened in the calendar app if that fails
    Copy image        the region itself, as a PNG (region mode only)
    Ask about this    screen-ask.py's question card on the region: a local
                      vision model answers (region mode only)
    Copy text         offered when tesseract read nothing: screen-ask.py ocr
      (vision model)  has the local vision model read the region instead

The local model: one LM Studio already has loaded, else the chat window's
default when it is local (llm.json, llm_models.py), else the first local
one; loaded with a TTL so it unloads itself when idle. All model calls run
off the GTK thread.
"""
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import urllib.parse
import urllib.request

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.expanduser("~/.config/waybar/scripts"))
import llm_models  # noqa: E402
import panelui  # noqa: E402


def _capture_settings():
    """capture-settings.py as a module (its name has a dash), for the OCR
    languages and the search engine; None if it is missing or broken, and
    then the old fixed choices below still work."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("capture_settings", os.path.join(HERE, "capture-settings.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


CAPTURE = _capture_settings()

RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
HEADER_CHARS = 60
MODEL_TTL = 900             # s idle before LM Studio unloads a model loaded here
OCR_LANGS = "eng+spa"       # when capture-settings.py cannot say


def ocr_langs():
    """The chosen languages that are installed: tesseract fails outright on
    a missing one instead of skipping it. None of them installed: the
    first one there is, so a region still reads as something."""
    wanted = (CAPTURE.values()[0]["ocr_langs"] if CAPTURE else OCR_LANGS).split("+")
    have = (CAPTURE.tesseract_langs() if CAPTURE else None) or []
    langs = [l for l in wanted if l in have] or have[:1] or wanted
    return "+".join(langs)


# -- getting the text --------------------------------------------------------------
def grab_region():
    """(text, png path) of a box the user drags, or (None, None) if cancelled."""
    geom = subprocess.run(["slurp"], capture_output=True, text=True).stdout.strip()
    if not geom:
        return None, None
    fd, png = tempfile.mkstemp(prefix="screen-actions-", suffix=".png", dir=RUNTIME)
    os.close(fd)
    if subprocess.run(["grim", "-g", geom, png]).returncode:
        return None, None
    return ocr(png), png


def ocr(png):
    out = subprocess.run(["tesseract", png, "-", "-l", ocr_langs(), "--psm", "6"],
                         capture_output=True, text=True).stdout
    return "\n".join(line.rstrip() for line in out.splitlines() if line.strip())


def grab_selection():
    for argv in (["wl-paste", "-p", "-n", "-t", "text"], ["wl-paste", "-n", "-t", "text"]):
        try:
            text = subprocess.run(argv, capture_output=True, text=True, timeout=2).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        if text.strip():
            return text.strip()
    return ""


# -- the local model -----------------------------------------------------------------
def api(path, payload=None, timeout=120):
    port = llm_models.server_port()
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(f"http://localhost:{port}{path}", data=data,
                                 headers={"content-type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def pick_model(status):
    """The LM Studio model key to ask, with the server up and it loaded."""
    try:
        models = api("/api/v0/models", timeout=3)["data"]
    except Exception:
        status("starting LM Studio…")
        try:
            # Inside its limits first (lmstudio.service), as llm_models.ensure_local does.
            llm_models._limits_module().ensure_daemon(status)
        except Exception:  # noqa: BLE001 -- a broken limits script: the old way
            pass
        llm_models._lms("server", "start", timeout=60)
        models = api("/api/v0/models", timeout=5)["data"]
    usable = [m for m in models if m.get("type") in ("llm", "vlm")]
    loaded = [m["id"] for m in usable if m.get("state") == "loaded"]
    if loaded:
        return loaded[0]
    default = llm_models.chosen("default")
    keys = [m["id"] for m in usable]
    key = default.ident if default and default.local and default.ident in keys else (keys[0] if keys else None)
    if not key:
        raise RuntimeError("LM Studio has no chat model")
    status(f"loading {key.split('/')[-1]}…")
    llm_models._lms("load", key, "-y", "--ttl", str(MODEL_TTL), timeout=300)
    return key


def ask(system, user, status):
    key = pick_model(status)
    status("thinking…")
    out = api("/v1/chat/completions", {
        # reasoning_effort none: thinking models (GLM, Qwen3) answer at once
        # instead of spending the whole budget on reasoning (LM Studio).
        "model": key, "temperature": 0.2, "max_tokens": 1500, "reasoning_effort": "none",
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
    text = out["choices"][0]["message"].get("content") or ""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def translate(text, status):
    return ask("You translate. If the text is mostly Spanish, translate it to English; otherwise "
               "translate it to Spanish. Reply with the translation only, no notes, keep line breaks.",
               text, status)


def extract_event(text, status):
    """{"title", "start", "end", "all_day"} from free text, or None."""
    now = dt.datetime.now()
    reply = ask("You read event details out of text. Today is "
                f"{now:%A %Y-%m-%d}, the time is {now:%H:%M}. Reply with ONLY a JSON object: "
                '{"title": str, "start": "YYYY-MM-DDTHH:MM" or "YYYY-MM-DD" for an all-day '
                'event, "end": same format or null}. Resolve relative dates ("tomorrow", '
                '"next Tuesday", "mañana"). If there is no date at all, reply {"title": null}.',
                text, status)
    m = re.search(r"\{.*\}", reply, re.S)
    if not m:
        return None
    try:
        ev = json.loads(m[0])
    except ValueError:
        return None
    if not ev.get("title") or not ev.get("start"):
        return None
    all_day = len(ev["start"]) == 10
    start = dt.datetime.fromisoformat(ev["start"])
    end = dt.datetime.fromisoformat(ev["end"]) if ev.get("end") else \
        start + (dt.timedelta(days=1) if all_day else dt.timedelta(hours=1))
    return {"title": ev["title"].strip(), "start": start, "end": end, "all_day": all_day}


# -- the calendar ----------------------------------------------------------------------
def ics_text(ev):
    import uuid
    if ev["all_day"]:
        when = f"DTSTART;VALUE=DATE:{ev['start']:%Y%m%d}\r\nDTEND;VALUE=DATE:{ev['end']:%Y%m%d}"
    else:
        when = f"DTSTART:{ev['start']:%Y%m%dT%H%M%S}\r\nDTEND:{ev['end']:%Y%m%dT%H%M%S}"
    title = ev["title"].replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", " ")
    return ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//screen-actions//EN\r\nBEGIN:VEVENT\r\n"
            f"UID:{uuid.uuid4()}\r\nDTSTAMP:{dt.datetime.utcnow():%Y%m%dT%H%M%SZ}\r\n"
            f"{when}\r\nSUMMARY:{title}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")


def add_event(ev):
    """Into Evolution's default calendar; an .ics opened by the calendar app
    if that fails. Returns a line to show."""
    vevent = ics_text(ev)
    try:
        gi.require_version("ECal", "2.0")
        gi.require_version("EDataServer", "1.2")
        gi.require_version("ICalGLib", "3.0")
        from gi.repository import ECal, EDataServer, ICalGLib
        reg = EDataServer.SourceRegistry.new_sync(None)
        src = reg.ref_default_calendar()
        client = ECal.Client.connect_sync(src, ECal.ClientSourceType.EVENTS, 5, None)
        comp = ICalGLib.Component.new_from_string(vevent).get_first_component(
            ICalGLib.ComponentKind.VEVENT_COMPONENT)
        client.create_object_sync(comp, ECal.OperationFlags.NONE, None)
        return f"added to {src.get_display_name()}"
    except Exception as exc:    # noqa: BLE001 -- any EDS failure: fall back to the file
        path = os.path.join(RUNTIME, "screen-actions-event.ics")
        with open(path, "w") as handle:
            handle.write(vevent)
        subprocess.Popen(["xdg-open", path], start_new_session=True)
        return f"opened as an .ics ({exc.__class__.__name__})"


def when_text(ev):
    if ev["all_day"]:
        return f"{ev['start']:%a %d %b} (all day)"
    return f"{ev['start']:%a %d %b, %H:%M}–{ev['end']:%H:%M}"


# -- the menu -----------------------------------------------------------------------------
class Menu(Gtk.Window):
    def __init__(self, text, png):
        super().__init__()
        self.text, self.png = text, png
        self.set_name("panel-window")
        self.set_app_paintable(True)
        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "waybar-panel")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.EXCLUSIVE)
        mon = focused_monitor()
        if mon:
            GtkLayerShell.set_monitor(self, mon)
        self.connect("key-press-event", self.on_key)
        self.connect("delete-event", Gtk.main_quit)

        self.card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.card.set_name("panel")
        self.card.set_size_request(420, -1)
        self.add(self.card)
        heading = Gtk.Label(label="SCREEN TEXT" if png else "SELECTED TEXT", xalign=0)
        heading.get_style_context().add_class("kb-heading")
        self.card.pack_start(heading, False, False, 0)
        flat = " ".join(text.split())
        found = flat[:HEADER_CHARS] + ("…" if len(flat) > HEADER_CHARS else "") if flat else \
            "no text found"
        self.header = Gtk.Label(label=found, xalign=0)
        self.header.get_style_context().add_class("ctl-sub")
        self.header.set_line_wrap(True)
        self.header.set_max_width_chars(50)
        self.card.pack_start(self.header, False, False, 0)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.card.pack_start(self.body, False, False, 0)
        self.show_actions()

    def clear(self):
        for child in self.body.get_children():
            self.body.remove(child)

    def button(self, caption, action):
        b = Gtk.Button(label=caption)
        b.get_style_context().add_class("dev-pick")
        b.get_child().set_xalign(0)
        b.connect("clicked", lambda _b: action())
        self.body.pack_start(b, False, False, 0)
        return b

    def note(self, text, selectable=False):
        lab = Gtk.Label(label=text, xalign=0)
        lab.get_style_context().add_class("ctl-sub")
        lab.set_line_wrap(True)
        lab.set_max_width_chars(50)
        lab.set_selectable(selectable)
        self.body.pack_start(lab, False, False, 0)
        return lab

    def show_actions(self):
        self.clear()
        has_text = bool(self.text.strip())
        actions = []
        if has_text:
            actions += [("Copy text", self.copy_text), ("Translate", self.translate),
                        ("Look it up", self.look_up), ("Add to calendar", self.calendar)]
        if self.png:
            actions.append(("Copy image", self.copy_image))
            actions.append(("Ask about this", lambda: self.hand_to_ask("image")))
            if not has_text:
                actions.insert(0, ("Copy text (vision model)", lambda: self.hand_to_ask("ocr")))
        if not actions:
            self.note("Nothing to act on.")
        first = None
        for caption, action in actions:
            b = self.button(caption, action)
            first = first or b
        self.body.show_all()
        if first:
            first.grab_focus()

    # -- actions --
    def copy_text(self):
        subprocess.run(["wl-copy"], input=self.text, text=True)
        Gtk.main_quit()

    def hand_to_ask(self, mode):
        """screen-ask.py (image | ocr) on a copy of the region -- this one
        goes when the menu closes -- which it deletes itself when done."""
        import shutil
        fd, copy = tempfile.mkstemp(prefix="screen-ask-", suffix=".png", dir=RUNTIME)
        os.close(fd)
        shutil.copyfile(self.png, copy)
        subprocess.Popen([sys.executable, os.path.join(HERE, "screen-ask.py"), mode, copy, "--delete"],
                         start_new_session=True)
        Gtk.main_quit()

    def copy_image(self):
        with open(self.png, "rb") as handle:
            subprocess.run(["wl-copy", "--type", "image/png"], stdin=handle)
        Gtk.main_quit()

    def look_up(self):
        query = " ".join(self.text.split())[:300]
        url = CAPTURE.search_url(query) if CAPTURE else "https://duckduckgo.com/?q=" + urllib.parse.quote(query)
        subprocess.Popen(["xdg-open", url],
                         start_new_session=True)
        Gtk.main_quit()

    def busy(self, first):
        self.clear()
        lab = self.note(first)
        self.body.show_all()
        return lambda text: GLib.idle_add(lab.set_text, text)

    def in_thread(self, work, done):
        def run():
            try:
                result = work()
                GLib.idle_add(done, result, None)
            except Exception as exc:    # noqa: BLE001 -- shown in the card
                GLib.idle_add(done, None, exc)
        threading.Thread(target=run, daemon=True).start()

    def translate(self):
        status = self.busy("translating…")

        def done(result, exc):
            self.clear()
            if exc or not result:
                self.note(f"Could not translate: {exc or 'no answer'}")
            else:
                self.note(result, selectable=True)
                self.button("Copy translation", lambda: (subprocess.run(["wl-copy"], input=result, text=True),
                                                         Gtk.main_quit()))
            self.button("Back", self.show_actions)
            self.body.show_all()
        self.in_thread(lambda: translate(self.text, status), done)

    def calendar(self):
        status = self.busy("reading the date…")

        def done(ev, exc):
            self.clear()
            if exc or not ev:
                self.note(f"No date found{': ' + str(exc) if exc else ''}.")
            else:
                self.note(f"{ev['title']}\n{when_text(ev)}")
                self.button("Add it", lambda: self.added(add_event(ev)))
            self.button("Back", self.show_actions)
            self.body.show_all()
        self.in_thread(lambda: extract_event(self.text, status), done)

    def added(self, line):
        self.clear()
        self.note(f"Event {line}.")
        self.body.show_all()
        GLib.timeout_add(1500, Gtk.main_quit)

    def on_key(self, _w, event):
        if event.keyval == Gdk.KEY_Escape:
            Gtk.main_quit()
            return True
        return False


def focused_monitor():
    try:
        out = subprocess.run(["hyprctl", "monitors", "-j"], capture_output=True, text=True, timeout=2).stdout
        origin = next(((m["x"], m["y"]) for m in json.loads(out) if m.get("focused")), None)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    display = Gdk.Display.get_default()
    for i in range(display.get_n_monitors()):
        mon = display.get_monitor(i)
        geo = mon.get_geometry()
        if (geo.x, geo.y) == origin:
            return mon
    return None


def main(argv):
    mode = argv[0] if argv else ""
    if mode == "region":
        text, png = grab_region()
        if text is None:
            return
    elif mode == "selection":
        text, png = grab_selection(), None
    else:
        sys.exit(__doc__)
    panelui.load_css()
    menu = Menu(text, png)
    menu.show_all()
    try:
        Gtk.main()
    finally:
        if png:
            try:
                os.remove(png)
            except OSError:
                pass


if __name__ == "__main__":
    main(sys.argv[1:])
