#!/usr/bin/env python3
"""Ask about the screen: grab part of it, ask a question in plain words
("what is this error", "translate it", "turn this table into CSV"), and a
LOCAL vision model in LM Studio answers. Nothing leaves the machine.

    screen-ask.py [region]          drag a box (slurp), then the question card
    screen-ask.py window            the focused window
    screen-ask.py screen            the focused screen
    screen-ask.py image PATH [--delete]
                                    a PNG already taken (screen-actions.py's "Ask
                                    about this"); --delete: it is ours to remove
    screen-ask.py text [--ask Q]    text on stdin instead of a picture (smart-
                                    clipboard.py's "Ask the local model" for errors)
    screen-ask.py ocr [region|window|screen|PATH [--delete]]
                                    copy the text in it: tesseract, or the vision
                                    model when tesseract is missing or reads nothing
    screen-ask.py render IMAGE OUT.png [ANSWER]
                                    the card drawn off screen into OUT.png (checking
                                    its look without a window or a keyboard grab)
    screen-ask.py which [--json]    the model it would answer with now, and why;
                                    loads nothing (Settings > Smart clipboard shows it)
    any of the first five take --ask QUESTION to ask at once

THE CARD is screen-actions.py's kind of window (panel.css, the theme's look,
a layer-shell card in the middle of the focused screen): the picture, quick
questions as buttons (What is this? / Explain this error / Translate /
Table to CSV / Summarise / Copy text), a box to type in, and a microphone
button that records until it is pressed again and hands the sound to
voice.py's daemon (`transcribe`; the recording is in tmpfs and deleted at
once). The answer comes in a scrolling box with Copy, Copy as CSV (when the
answer holds a table: a Markdown table, a ```csv block, tab- or comma-
separated lines -- to_csv()) and Ask a follow-up (the conversation, picture
included, is kept for the next question). Enter asks, Escape closes.

WHICH MODEL (pick_model(), using llm_models.py and llm-gpu.py's fit_now
the way llm-worker.py's ready() does): LM Studio's own list
(/api/v0/models) says which models take pictures (type "vlm": gemma-4-e4b,
and the Qwen3.6 / 3.8 27Bs, which ship an mmproj). In order:
    1. one already loaded: the cheapest choice, it costs nothing more
    2. else the "quick", then "worker", then "default" setting (Settings > AI
       & models), then the smallest -- the first that FITS on the graphics card
       next to what is loaded now; ensure_local() loads it with a TTL
Never: a cloud model, unloading anything to make room (a model that would
not fit is skipped, and the card says which and why), or anything at all in
gamemode. Text-only questions (`text`) take any chat model the same way.

PRIVACY. The capture is refused (nothing is taken) when a password manager,
a private-browsing window or an app on the Privacy page's private list is in
it (smart-clipboard.py's private_focus(): activity-log.py's is_private plus
the password managers). Screenshots go to $XDG_RUNTIME_DIR (tmpfs, mode
600) and are deleted when the card closes -- also on Escape, an error or a
SIGTERM; the picture goes to the model as a data URL, scaled to MAX_SIDE.
"""
import base64
import csv
import importlib.util
import io
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.expanduser("~/.config/waybar/scripts"))
import llm_models  # noqa: E402

RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
MAX_SIDE = 1600             # px, the long side of the picture sent to the model
MAX_TOKENS = 1500
MAX_RECORD_S = 60
TEXT_CHARS = 20_000
ROLES = ("quick", "worker", "default")
SYSTEM = ("You answer questions about something on the user's screen: a screenshot, or text they "
          "copied. Be concise and concrete; no preamble. Answer in the language of the question. "
          "When asked for a table, CSV or spreadsheet, reply with only the CSV inside a ```csv block. "
          "When asked to translate, give only the translation. If the picture does not show what is "
          "asked about, say so instead of guessing.")
QUICK = [("What is this?", "What is this? Explain briefly."),
         ("Explain this error", "What does this error mean, and how do I fix it? Be brief."),
         ("Translate", "Translate the text in this to English (or to Spanish if it is already English). "
                       "Only the translation."),
         ("Table to CSV", "Turn the table in this into CSV."),
         ("Summarise", "Summarise this in a few bullet points.")]
OCR_PROMPT = ("Transcribe all the text in this image exactly as written, keeping the line breaks. "
              "Reply with the text only.")


def _module(name, filename):
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return mod


def worker():
    return _module("llm_worker", "llm-worker.py")


def smartclip():
    return _module("smart_clipboard", "smart-clipboard.py")


def notify(title, body="", urgency="normal"):
    subprocess.run(["notify-send", "-a", "Ask about the screen", "-i", "dialog-question", "-u", urgency,
                    "-t", "5000", title, body], capture_output=True, timeout=5)


# -- tables -------------------------------------------------------------------------------
def _csv_text(rows):
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerows(rows)
    return out.getvalue()


def to_csv(answer):
    """The table in an answer as CSV text, or None when there is none: a
    ```csv block, a Markdown table, or two or more tab- or comma-separated
    lines with the same number of columns."""
    block = re.search(r"```(?:csv|CSV)?[ \t]*\n(.*?)```", answer, re.S)
    if block:
        lines = [l for l in block[1].strip().splitlines() if l.strip()]
        if len(lines) >= 2 and all("," in l for l in lines):
            return "\n".join(lines) + "\n"
    rows = []
    for line in answer.splitlines():
        s = line.strip()
        if s.count("|") >= 2 or (s.startswith("|") and s.endswith("|") and len(s) > 2):
            if re.fullmatch(r"\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?", s):
                continue            # the |---|---| line under the header
            cells = [c.strip() for c in s.strip("|").split("|")]
            rows.append(cells)
        elif rows:
            break
    if len(rows) >= 2 and len({len(r) for r in rows}) == 1 and len(rows[0]) >= 2:
        return _csv_text(rows)
    for sep in ("\t", ","):
        lines = [l for l in answer.strip().splitlines() if l.strip()]
        if len(lines) >= 2 and all(l.count(sep) == lines[0].count(sep) >= 1 for l in lines):
            if sep == ",":
                return "\n".join(lines) + "\n"
            return _csv_text([l.split("\t") for l in lines])
    return None


# -- what may be captured ------------------------------------------------------------------------
def hyprctl_json(*args):
    try:
        out = subprocess.run(["hyprctl", *args, "-j"], capture_output=True, text=True, timeout=3).stdout
        return json.loads(out or "null")
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def parse_geometry(text):
    """slurp's "x,y wxh" -> (x, y, w, h), or None."""
    m = re.fullmatch(r"\s*(-?\d+),(-?\d+) (\d+)x(\d+)\s*", text or "")
    return tuple(int(v) for v in m.groups()) if m else None


def overlaps(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def visible_workspaces(monitors):
    out = set()
    for m in monitors or []:
        for key in ("activeWorkspace", "specialWorkspace"):
            ws = (m.get(key) or {}).get("id")
            if ws:
                out.add(ws)
    return out


def private_in(clients, rect, workspaces, is_private):
    """The private windows (class or title) a capture of `rect` would show:
    on a visible workspace and overlapping it. rect None: all of them."""
    out = []
    for c in clients or []:
        if (c.get("workspace") or {}).get("id") not in workspaces or c.get("hidden"):
            continue
        box = (*c.get("at", (0, 0)), *c.get("size", (0, 0)))
        if rect is not None and not overlaps(rect, box):
            continue
        if is_private(c):
            out.append(c.get("class") or c.get("title") or "a private window")
    return out


def _is_private(window):
    return smartclip().private_focus(window)


def screen_rect(monitor):
    return (monitor["x"], monitor["y"], round(monitor["width"] / monitor.get("scale", 1)),
            round(monitor["height"] / monitor.get("scale", 1)))


def capture(mode):
    """(png path, None) or (None, why). Refused when a private window is in it."""
    clients = hyprctl_json("clients") or []
    monitors = hyprctl_json("monitors") or []
    shown = visible_workspaces(monitors)
    argv = ["grim"]
    if mode == "window":
        win = hyprctl_json("activewindow")
        if not isinstance(win, dict) or not win.get("size"):
            return None, "no window has the focus"
        if _is_private(win):
            return None, f"{win.get('class') or 'that window'} is private: not captured"
        x, y = win["at"]
        w, h = win["size"]
        argv += ["-g", f"{x},{y} {w}x{h}"]
    elif mode == "screen":
        mon = next((m for m in monitors if m.get("focused")), None)
        if not mon:
            return None, "no focused screen"
        hidden = private_in(clients, screen_rect(mon), shown, _is_private)
        if hidden:
            return None, f"{hidden[0]} is on that screen: not captured"
        argv += ["-o", mon["name"]]
    else:
        geom = subprocess.run(["slurp"], capture_output=True, text=True).stdout.strip()
        rect = parse_geometry(geom)
        if not rect:
            return None, ""             # cancelled: no message
        hidden = private_in(clients, rect, shown, _is_private)
        if hidden:
            return None, f"{hidden[0]} is in that part of the screen: not captured"
        argv += ["-g", geom]
    fd, png = tempfile.mkstemp(prefix="screen-ask-", suffix=".png", dir=RUNTIME)
    os.close(fd)
    if subprocess.run(argv + [png], capture_output=True).returncode:
        _remove(png)
        return None, "grim could not take the screenshot"
    return png, None


def owned(path):
    """--delete only ever removes a screenshot handed over by screen-actions.py
    (screen-ask-*.png in $XDG_RUNTIME_DIR), never just any file named."""
    real = os.path.realpath(path or "")
    return (os.path.dirname(real) == os.path.realpath(RUNTIME)
            and os.path.basename(real).startswith("screen-ask-"))


def _remove(path):
    if path:
        try:
            os.remove(path)
        except OSError:
            pass


def image_url(png):
    """The picture as a data URL, scaled down to MAX_SIDE (Pillow when there
    is one; else as it is)."""
    with open(png, "rb") as handle:
        data = handle.read()
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        if max(img.size) > MAX_SIDE:
            img.thumbnail((MAX_SIDE, MAX_SIDE))
            out = io.BytesIO()
            img.convert("RGB").save(out, "PNG", optimize=True)
            data = out.getvalue()
    except Exception:       # noqa: BLE001 -- no Pillow / odd file: send it as it is
        pass
    return "data:image/png;base64," + base64.b64encode(data).decode()


# -- the model -------------------------------------------------------------------------------------
def server_rows(start=True, status=lambda text: None):
    """LM Studio's model list (/api/v0/models: type llm / vlm, state), the
    server started first when it is down and `start`; None when it is not
    reachable."""
    url = f"http://localhost:{llm_models.server_port()}/api/v0/models"
    for attempt in range(2):
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                return json.load(resp).get("data") or []
        except (OSError, ValueError):
            if attempt or not start or not os.access(llm_models.LMS, os.X_OK):
                return None
            status("starting LM Studio…")
            try:
                llm_models._lms("server", "start", timeout=60)
            except (OSError, subprocess.SubprocessError):
                return None
    return None


def candidates(rows, prefer, sizes, need_vision=True):
    """[(key, loaded)] best first: the loaded ones, then `prefer` (the role
    settings' keys) in order, then the smallest."""
    kinds = ("vlm",) if need_vision else ("llm", "vlm")
    usable = [r for r in rows if r.get("type") in kinds and r.get("id")]

    def rank(r):
        key = r["id"]
        return (r.get("state") != "loaded", prefer.index(key) if key in prefer else len(prefer),
                sizes.get(key, float("inf")), key)
    return [(r["id"], r.get("state") == "loaded") for r in sorted(usable, key=rank)]


def _prefer():
    out = []
    for role in ROLES:
        try:
            model = llm_models.chosen(role)
        except Exception:   # noqa: BLE001
            model = None
        if model is not None and model.local and model.ident not in out:
            out.append(model.ident)
    return out


def _sizes():
    return {r["modelKey"]: r.get("sizeBytes") or 0 for r in llm_models._read_cache().get("models") or []}


def _model(key):
    return llm_models.resolve(key) or llm_models.Model(key.split("/")[-1], key, "local", key)


def _fit(model):
    try:
        return llm_models._gpu_module().fit_now(model)
    except Exception:       # noqa: BLE001 -- the calculator is advice
        return None


def pick_model(status=lambda text: None, need_vision=True, load=True):
    """(LM Studio key, None) ready to ask, or (None, why). load=False only
    says what it would pick ("which")."""
    if llm_models._gamemode_on():
        return None, "gamemode is on: the graphics card belongs to the game"
    rows = server_rows(start=load, status=status)
    if rows is None:
        return None, ("LM Studio is not running; it is started when you ask" if not load else
                      "LM Studio's server did not start (lms server start)")
    cands = candidates(rows, _prefer(), _sizes(), need_vision)
    if not cands:
        return None, ("no installed model takes pictures (LM Studio: a model with an mmproj, e.g. "
                      "gemma-4-e4b)" if need_vision else "LM Studio has no chat model")
    for key, loaded in cands:
        if loaded:
            return key, None
    skipped = []
    for key, _loaded in cands:
        model = _model(key)
        verdict = _fit(model)
        if verdict and verdict["verdict"] == "won't fit":
            skipped.append(model.name)
            continue
        if not load:
            return key, None
        ok, why = llm_models.ensure_local(model, status)
        if ok:
            return key, None
        skipped.append(f"{model.name} ({why})")
    big = ", ".join(r["id"].split("/")[-1] for r in rows if r.get("state") == "loaded") or "other programs"
    return None, (f"no {'vision ' if need_vision else ''}model fits on the graphics card next to {big} "
                  f"(tried {', '.join(skipped)}); nothing was unloaded to make room")


def ask(key, messages):
    """llm-worker.py's ask() with the whole conversation (its `extra` takes
    the place of the one-message prompt it builds)."""
    model = llm_models.Model(key.split("/")[-1], key, "local", key)
    return worker().ask(model, "", SYSTEM, extra={
        "messages": [{"role": "system", "content": SYSTEM}] + messages,
        # reasoning_effort none: a thinking model (Qwen3) answers at once
        "reasoning_effort": "none", "max_tokens": MAX_TOKENS})


def first_message(question, png=None, text=None):
    if png:
        return {"role": "user", "content": [{"type": "text", "text": question},
                                            {"type": "image_url", "image_url": {"url": image_url(png)}}]}
    return {"role": "user", "content": f"{question}\n\n---\n{(text or '')[:TEXT_CHARS]}"}


# -- copying text ------------------------------------------------------------------------------------
def ocr_text(png, status=lambda text: None):
    """(text, how): tesseract in Settings' languages (screen-actions.py's
    ocr()), else the vision model."""
    if shutil.which("tesseract"):
        try:
            text = _module("screen_actions", "screen-actions.py").ocr(png)
        except Exception:   # noqa: BLE001 -- fall through to the model
            text = ""
        if text.strip():
            return text, "tesseract"
    key, why = pick_model(status)
    if not key:
        return "", why
    status("reading the text…")
    return ask(key, [first_message(OCR_PROMPT, png)]), key.split("/")[-1]


def ocr_command(arg, delete=False):
    own = arg in ("", "region", "window", "screen")
    if own:
        png, why = capture(arg or "region")
        if not png:
            if why:
                notify("Nothing copied", why)
            return
    else:
        png = arg
    try:
        text, how = ocr_text(png)
    except Exception as exc:    # noqa: BLE001 -- LM Studio gone mid-way, a bad file: say so
        text, how = "", f"{exc.__class__.__name__}: {exc}"
    finally:
        if own or (delete and owned(png)):
            _remove(png)
    if not text.strip():
        notify("No text found", how if how not in ("tesseract",) else "")
        return
    subprocess.run(["wl-copy"], input=text, text=True)
    flat = " ".join(text.split())
    notify("Text copied", f"{flat[:140]}{'…' if len(flat) > 140 else ''}\n(read by {how})")


# -- the card -----------------------------------------------------------------------------------------
def card_main(png=None, text=None, question=None, render=None):
    """The card. render=(out.png, answer): drawn off screen into out.png
    instead (no layer surface, no keyboard grab), with that answer shown."""
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("GdkPixbuf", "2.0")
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, GtkLayerShell, Pango
    import panelui

    class Card(Gtk.OffscreenWindow if render else Gtk.Window):
        def __init__(self):
            super().__init__()
            self.png, self.text = png, text
            self.messages, self.answer, self.busy = [], "", False
            self.rec = self.rec_path = None
            self.set_name("panel-window")
            self.set_app_paintable(True)
            visual = self.get_screen().get_rgba_visual()
            if visual:
                self.set_visual(visual)
            if not render:
                GtkLayerShell.init_for_window(self)
                GtkLayerShell.set_namespace(self, "waybar-panel")
                GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
                GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.EXCLUSIVE)
                mon = smartclip()._focused_monitor(Gdk)
                if mon:
                    GtkLayerShell.set_monitor(self, mon)
            self.connect("key-press-event", self.on_key)
            self.connect("delete-event", lambda *_a: self.quit())

            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            card.set_name("panel")
            card.set_size_request(560, -1)
            self.add(card)
            heading = Gtk.Label(label="ASK ABOUT THE SCREEN" if png else "ASK ABOUT THIS", xalign=0)
            heading.get_style_context().add_class("kb-heading")
            card.pack_start(heading, False, False, 0)
            if png:
                try:
                    pix = GdkPixbuf.Pixbuf.new_from_file_at_scale(png, 528, 200, True)
                    card.pack_start(Gtk.Image.new_from_pixbuf(pix), False, False, 0)
                except GLib.Error:
                    pass
            else:
                card.pack_start(self.sub(" ".join((text or "").split())[:240] + "…"
                                         if len(text or "") > 240 else (text or "").strip()), False, False, 0)
            chips = Gtk.FlowBox()
            chips.set_selection_mode(Gtk.SelectionMode.NONE)
            chips.set_max_children_per_line(6)
            chips.set_column_spacing(4)
            chips.set_row_spacing(4)
            for caption, prompt in QUICK:
                if not png and caption == "Table to CSV":
                    continue
                chips.add(self.button(caption, lambda p=prompt: self.ask(p)))
            if png:
                chips.add(self.button("Copy text", self.copy_text))
            card.pack_start(chips, False, False, 0)

            line = Gtk.Box(spacing=6)
            self.entry = Gtk.Entry()
            self.entry.set_placeholder_text("Ask about it…  (Enter)")
            self.entry.connect("activate", lambda e: self.ask(e.get_text()))
            line.pack_start(self.entry, True, True, 0)
            if shutil.which("pw-record"):
                self.mic = self.button("", self.toggle_mic)
                self.mic.set_tooltip_text("Say the question (press again to stop)")
                line.pack_start(self.mic, False, False, 0)
            card.pack_start(line, False, False, 0)
            self.status = self.sub("")
            card.pack_start(self.status, False, False, 0)

            # A selectable label, not a TextView: it takes the theme's colours
            # (a TextView paints its own white page) and its natural height.
            self.view = Gtk.Label(xalign=0, yalign=0)
            self.view.set_selectable(True)
            self.view.set_line_wrap(True)
            self.view.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            self.view.set_max_width_chars(70)
            self.view.set_margin_end(10)
            self.scroll = Gtk.ScrolledWindow()
            self.scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            self.scroll.set_min_content_height(80)
            self.scroll.set_max_content_height(420)
            self.scroll.set_propagate_natural_height(True)
            self.scroll.add(self.view)
            self.scroll.set_no_show_all(True)
            card.pack_start(self.scroll, True, True, 0)
            self.after = Gtk.Box(spacing=6)
            self.after.set_no_show_all(True)
            self.copy_btn = self.button("Copy", lambda: self.copy(self.answer, "Answer copied."))
            self.csv_btn = self.button("Copy as CSV", lambda: self.copy(to_csv(self.answer) or "", "CSV copied."))
            self.follow = self.button("Ask a follow-up", self.entry.grab_focus)
            for b in (self.copy_btn, self.csv_btn, self.follow):
                self.after.pack_start(b, False, False, 0)
            self.after.pack_end(self.button("Close", self.quit), False, False, 0)
            card.pack_start(self.after, False, False, 0)
            self.entry.grab_focus()
            if question:
                GLib.idle_add(lambda: (self.ask(question), False)[1])

        # -- pieces --
        def sub(self, text):
            lab = Gtk.Label(label=text, xalign=0)
            lab.get_style_context().add_class("ctl-sub")
            lab.set_line_wrap(True)
            lab.set_max_width_chars(70)
            return lab

        def button(self, caption, action):
            b = Gtk.Button(label=caption)
            b.get_style_context().add_class("dev-pick")
            b.connect("clicked", lambda _b: action())
            return b

        def say(self, text):
            GLib.idle_add(self.status.set_text, text)

        def show_answer(self, text, error=False):
            self.answer = "" if error else text
            self.view.set_text(text)
            # propagate-natural-height does not follow a wrapping label: size
            # the box from the wrapped line count, up to its maximum
            rows = sum(max(1, -(-len(l) // 66)) for l in text.splitlines() or [""])
            self.scroll.set_min_content_height(min(420, max(60, rows * 21 + 8)))
            for part in (self.scroll, self.after):  # show_all() skips a no-show-all widget
                part.set_no_show_all(False)
                part.show_all()
            for b in (self.copy_btn, self.follow):
                b.set_visible(not error)
            self.csv_btn.set_visible(not error and to_csv(text) is not None)
            self.entry.set_placeholder_text("Ask a follow-up…  (Enter)")
            self.entry.grab_focus()

        # -- asking --
        def ask(self, question):
            question = (question or "").strip()
            if not question or self.busy:
                return
            self.busy = True
            self.entry.set_text("")
            self.status.set_text("finding a model…")
            if not self.messages:
                msg = first_message(question, self.png, self.text)
            else:
                msg = {"role": "user", "content": question}
            history = self.messages + [msg]

            def work():
                key, why = pick_model(self.say, need_vision=bool(self.png))
                if not key:
                    raise RuntimeError(why)
                self.say(f"{key.split('/')[-1]} is thinking…")
                started = time.time()
                answer = ask(key, history)
                return answer, f"{key.split('/')[-1]} · {time.time() - started:.1f} s · local"

            def done(result, exc):
                self.busy = False
                if exc:
                    self.status.set_text("")
                    self.show_answer(f"Could not answer: {exc}", error=True)
                    return
                answer, line = result
                self.messages = history + [{"role": "assistant", "content": answer}]
                self.status.set_text(line)
                self.show_answer(answer or "(no answer)")
            self.in_thread(work, done)

        def copy_text(self):
            if self.busy:
                return
            self.busy = True
            self.status.set_text("reading the text…")

            def done(result, exc):
                self.busy = False
                text, how = result if result else ("", str(exc))
                if not text.strip():
                    self.status.set_text("")
                    self.show_answer(f"No text found{': ' + how if how != 'tesseract' else ''}.", error=True)
                    return
                subprocess.run(["wl-copy"], input=text, text=True)
                self.status.set_text(f"copied · read by {how}")
                self.show_answer(text)
            self.in_thread(lambda: ocr_text(self.png, self.say), done)

        def copy(self, text, line):
            if text:
                subprocess.run(["wl-copy"], input=text, text=True)
                self.status.set_text(line)

        def in_thread(self, work, done):
            def run():
                try:
                    result = work()
                    GLib.idle_add(done, result, None)
                except Exception as exc:    # noqa: BLE001 -- shown in the card
                    GLib.idle_add(done, None, exc)
            threading.Thread(target=run, daemon=True).start()

        # -- the microphone --
        def toggle_mic(self):
            if self.rec:
                self.stop_mic()
                return
            fd, self.rec_path = tempfile.mkstemp(prefix="screen-ask-", suffix=".raw", dir=RUNTIME)
            self.rec = subprocess.Popen(["pw-record", "--rate", "16000", "--channels", "1", "--format", "s16",
                                         "--raw", "-P", '{ media.name="Ask about the screen" }', "-"],
                                        stdout=fd, stderr=subprocess.DEVNULL)
            os.close(fd)
            self.mic.get_style_context().add_class("active")
            self.status.set_text("listening… press the microphone again to stop")
            rec = self.rec
            GLib.timeout_add_seconds(MAX_RECORD_S, lambda: (self.rec is rec and self.stop_mic(), False)[1])

        def stop_mic(self, keep=True):
            proc, path, self.rec = self.rec, self.rec_path, None
            if not proc:
                return
            proc.send_signal(signal.SIGINT)
            try:
                proc.wait(3)
            except subprocess.TimeoutExpired:
                proc.kill()
            self.mic.get_style_context().remove_class("active")
            if not keep:
                _remove(path)
                return
            self.status.set_text("transcribing…")

            def work():
                try:
                    voice = _module("voice_client", "voice.py")
                    return voice.request({"cmd": "transcribe", "path": path}, timeout=180)
                finally:
                    _remove(path)

            def done(answer, exc):
                answer = answer or {}
                said = (answer.get("text") or "").strip()
                if exc or answer.get("error") or not said:
                    self.status.set_text(f"voice: {exc or answer.get('error') or 'heard nothing'}")
                    return
                self.status.set_text("")
                self.entry.set_text(said)
                self.entry.set_position(-1)
                self.entry.grab_focus()
            self.in_thread(work, done)

        def on_key(self, _w, event):
            if event.keyval == Gdk.KEY_Escape:
                self.quit()
                return True
            return False

        def quit(self):
            self.stop_mic(keep=False)
            Gtk.main_quit()

    panelui.load_css()
    card = Card()
    signal.signal(signal.SIGTERM, lambda *_a: GLib.idle_add(card.quit))
    if render and render[1]:
        card.show_answer(render[1])
    card.show_all()
    if render:
        for _ in range(60):
            while Gtk.events_pending():
                Gtk.main_iteration()
            time.sleep(0.02)
        card.get_pixbuf().savev(render[0], "png", [], [])
        return
    Gtk.main()


# -- the command line ------------------------------------------------------------------------------------
def which():
    key, why = pick_model(load=False)
    rows = server_rows(start=False) or []
    loaded = any(r.get("id") == key and r.get("state") == "loaded" for r in rows)
    return {"model": key, "loaded": loaded, "why": why or "",
            "vision": [r["id"] for r in rows if r.get("type") == "vlm"]}


def main(argv):
    question = None
    if "--ask" in argv:
        i = argv.index("--ask")
        question = " ".join(argv[i + 1:i + 2])
        argv = argv[:i] + argv[i + 2:]
    mode = argv[0] if argv else "region"
    # SIGTERM unwinds like an error, so the finally blocks delete the screenshot
    # (the card sets its own handler)
    signal.signal(signal.SIGTERM, lambda *_a: sys.exit(143))
    if mode == "which":
        data = which()
        if "--json" in argv:
            print(json.dumps(data))
        else:
            print(f"{data['model'] or 'none'}{' (loaded)' if data['loaded'] else ''}"
                  f"{'  -- ' + data['why'] if data['why'] else ''}")
        return
    if mode == "render" and len(argv) >= 3:
        card_main(argv[1], None, None, render=(argv[2], " ".join(argv[3:])))
        return
    if mode == "ocr":
        ocr_command(argv[1] if len(argv) > 1 else "", delete="--delete" in argv)
        return
    if llm_models._gamemode_on():
        if mode == "image" and "--delete" in argv and len(argv) > 1 and owned(argv[1]):
            _remove(argv[1])        # handed over to us: still ours to delete
        notify("Not in gamemode", "Asking about the screen needs the graphics card, which the game has.")
        return
    png, text, own = None, None, False
    if mode == "text":
        text = sys.stdin.read()
        if not text.strip():
            return
    elif mode == "image":
        if len(argv) < 2 or not os.path.isfile(argv[1]):
            sys.exit("screen-ask: image PATH [--delete]")
        png, own = argv[1], "--delete" in argv and owned(argv[1])
    elif mode in ("region", "window", "screen"):
        png, why = capture(mode)
        own = True
        if not png:
            if why:
                notify("Not captured", why)
            return
    else:
        sys.exit(__doc__)
    try:
        card_main(png, text, question)
    finally:
        if own:
            _remove(png)


if __name__ == "__main__":
    main(sys.argv[1:])
